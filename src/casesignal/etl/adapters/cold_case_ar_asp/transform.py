"""Transform stage for the AR ASP adapter."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_ar_asp.county_fips import lookup as ar_fips
from casesignal.etl.services.normalizers import clean_sentinel, normalize_gender
from casesignal.etl.services.photo_helpers import safe_filename
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
    load_tier2_v4_prompt_template,
)
from casesignal.extraction.cold_case.queue_handler import enqueue_extraction_job

logger = logging.getLogger(__name__)

_AR_STATE = "AR"
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_TIER2_PROMPT_HASH = compute_prompt_hash(load_tier2_v4_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()

_MONTH_YEAR_RE = re.compile(r"^(?P<month>[A-Za-z]+)\s+(?P<year>(?:19|20)\d{2})$")


def normalize_ar_date(raw: str | None) -> str | None:
    """AR ASP dates → ISO. Formats seen live: 'January 14, 1991',
    '07/29/1994', 'December 2017', 'Unknown'.

    Month-year gets day 01 — same accepted false-precision trade as
    normalize_date's year-only → Jan 1 fallback; losing the whole date is
    worse for correlation's time-window math than a synthetic day.
    """
    value = clean_sentinel(raw)
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    m = _MONTH_YEAR_RE.match(value)
    if m:
        try:
            return datetime.strptime(f"{m.group('month')} 1, {m.group('year')}", "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    return None


def derive_case_type(date_label: str | None) -> str:
    if date_label == "missing":
        return "missing_person"
    if date_label == "death":
        return "homicide"
    return "cold_case"


def assign_source_case_ids(entries: list[dict[str, Any]]) -> None:
    """Set entry['source_case_id']: CASE NUMBER when present AND unique
    across the scrape; otherwise the (already lowercased, URL-unique) slug.

    Keeps the validation gate's (state, source_case_id) anchor stable: a
    missing or colliding case number degrades only the affected entries.
    """
    counts: dict[str, int] = {}
    for e in entries:
        cn = clean_sentinel(e.get("case_number"))
        if cn:
            counts[cn] = counts.get(cn, 0) + 1
    for e in entries:
        cn = clean_sentinel(e.get("case_number"))
        if cn and counts[cn] == 1:
            e["source_case_id"] = cn
        else:
            e["source_case_id"] = e["slug"]
            if cn:
                logger.warning(
                    "AR ASP: duplicate case number %r; using slug %r", cn, e["slug"]
                )

    seen_ids: dict[str, dict[str, Any]] = {}
    for e in entries:
        sid = e["source_case_id"]
        if sid in seen_ids:
            raise ValueError(
                f"AR ASP: assigned source_case_id {sid!r} collides across entries "
                f"(slugs {seen_ids[sid]['slug']!r} and {e['slug']!r}); "
                "a CASE NUMBER equals another entry's slug (or vice versa). "
                "Refusing to proceed — this would silently drop a row via ON CONFLICT."
            )
        seen_ids[sid] = e


def build_extraction_text(narrative: str, cause: str | None) -> str:
    """Stored source text = narrative + a final cause line, so Tier-1
    weapon offsets point into real stored text for the reveal-source UI."""
    c = clean_sentinel(cause)
    if not c:
        return narrative
    line = f"Cause of death: {c.rstrip('.')}."
    return f"{narrative}\n\n{line}" if narrative else line


# Generational suffixes that ride with the surname ("Avery L. Sampleton Jr."
# → last name "Sampleton Jr."). Lowercased, period-stripped for matching; 9 of
# the 148 live AR corpus names end in Jr./Sr.
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})


def _split_display_name(name: str | None) -> tuple[str, str]:
    """AR names are display-order ('Ada Ann Exampleton Example'): last token is
    the last name, except a generational suffix stays attached to the surname.
    Multi-victim 'Alf and Bea Testford' intentionally lands as one row —
    reconcile_victims' garbled-row detection (' and ') splits it from the
    Tier-2 roster."""
    parts = [p.strip() for p in (name or "").split() if p.strip()]
    if not parts:
        return "Unknown", ""
    if len(parts) == 1:
        return parts[0], ""
    if len(parts) >= 3 and parts[-1].rstrip(".").lower() in _NAME_SUFFIXES:
        return " ".join(parts[:-2]), f"{parts[-2]} {parts[-1]}"
    return " ".join(parts[:-1]), parts[-1]


def transform_ar(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_ar_asp_dv{context.dataset_version_id}"
    cases_inserted = 0
    photos_inserted = 0
    extraction_jobs = 0
    geocoding_jobs = 0
    unknown_counties = 0

    with session_factory() as session:
        try:
            _delete_existing_canonical_rows(session, dataset_version_id=context.dataset_version_id)
            raw_rows = session.execute(
                text(f"""
                    SELECT dataset_version_id, source_case_id, slug, case_name, case_type,
                           age_text, race, sex, date_label, date_text, cause, county,
                           case_number, narrative, contact_text, contact_agency,
                           contact_phone, photos_json, source_detail_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                incident_date_iso = normalize_ar_date(r.date_text)
                county = clean_sentinel(r.county)
                county_fips = ar_fips(county)
                if county and county_fips is None:
                    unknown_counties += 1
                    logger.warning(
                        "AR ASP: unknown county %r on %s", county, r.source_case_id
                    )
                about_text = build_extraction_text(r.narrative or "", r.cause)

                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=r.case_name,
                    case_type=r.case_type or "cold_case",
                    incident_date_iso=incident_date_iso,
                    county_fips=county_fips,
                    about_text=about_text,
                )
                cases_inserted += 1

                _insert_victim(session, case_id=case_id, r=r)
                _insert_contact(session, case_id=case_id, r=r)

                for i, photo in enumerate(json.loads(r.photos_json) if r.photos_json else []):
                    _insert_photo(
                        session,
                        case_id=case_id,
                        source_case_id=r.source_case_id,
                        photo=photo,
                        is_primary=(i == 0),
                    )
                    photos_inserted += 1

                for tier, prompt_hash in ((1, _TIER1_PROMPT_HASH), (2, _TIER2_PROMPT_HASH)):
                    enqueue_extraction_job(
                        session,
                        case_id=case_id,
                        prompt_hash=prompt_hash,
                        model_id=_PINNED_MODEL_ID,
                        prompt_tier=tier,
                    )
                    extraction_jobs += 1

                address_text = f"{county} County, AR" if county else "Arkansas"
                session.execute(
                    text("""
                        INSERT INTO cold_case.geocoding_job
                            (case_id, address_text, state_code, zip_code, county_fips)
                        VALUES (:cid, :addr, :state, NULL, :fips)
                    """),
                    {"cid": case_id, "addr": address_text, "state": _AR_STATE, "fips": county_fips},
                )
                geocoding_jobs += 1

            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("transform", cases_inserted)
    log = context.logger or logger
    log.info(
        "AR ASP transform: %d cases (%d unknown counties), %d photos, "
        "%d extraction jobs, %d geocoding jobs",
        cases_inserted, unknown_counties, photos_inserted, extraction_jobs, geocoding_jobs,
    )


def _delete_existing_canonical_rows(session: Session, *, dataset_version_id: int) -> None:
    session.execute(
        text("""
            DELETE FROM cold_case.extraction_job
            USING cold_case.cases
            WHERE extraction_job.case_id = cases.case_id
              AND cases.dataset_version_id = :dv
        """),
        {"dv": dataset_version_id},
    )
    session.execute(
        text("""
            DELETE FROM cold_case.geocoding_job
            USING cold_case.cases
            WHERE geocoding_job.case_id = cases.case_id
              AND cases.dataset_version_id = :dv
        """),
        {"dv": dataset_version_id},
    )
    session.execute(
        text("DELETE FROM cold_case.cases WHERE dataset_version_id = :dv"),
        {"dv": dataset_version_id},
    )


def _insert_case(
    session: Session,
    *,
    dataset_version_id: int,
    source_case_id: str,
    case_name: str,
    case_type: str,
    incident_date_iso: str | None,
    county_fips: str | None,
    about_text: str,
) -> int:
    year = None
    if incident_date_iso:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None
    slug_base = build_case_slug(case_name=case_name, city=None, state=_AR_STATE, year=year)
    slug = resolve_slug_collision(session, slug_base)

    return int(
        session.execute(
            text("""
                INSERT INTO cold_case.cases (
                    dataset_version_id, source_case_id, slug,
                    case_name, case_type, state, city, source_county_fips,
                    incident_date, address,
                    about_text, latitude, longitude, geocode_precision,
                    incident_date_source, address_source
                )
                VALUES (
                    :dv, :scid, :slug,
                    :name, :case_type, :state, NULL, :fips,
                    :date, NULL,
                    :about, NULL, NULL, NULL,
                    CASE WHEN :date IS NULL THEN NULL ELSE 'source' END,
                    NULL
                )
                RETURNING case_id
            """),
            {
                "dv": dataset_version_id,
                "scid": source_case_id,
                "slug": slug,
                "name": case_name,
                "case_type": case_type,
                "state": _AR_STATE,
                "fips": county_fips,
                "date": incident_date_iso,
                "about": about_text,
            },
        ).scalar_one()
    )


def _insert_victim(session: Session, *, case_id: int, r: Row[Any]) -> None:
    first_name, last_name = _split_display_name(clean_sentinel(r.case_name))
    gender = normalize_gender(r.sex)
    race = clean_sentinel(r.race)
    age_text = clean_sentinel(r.age_text)
    session.execute(
        text("""
            INSERT INTO cold_case.victim (
                case_id, first_name, last_name, gender,
                age_text, race,
                height_text, weight_num,
                eye_color, hair_color,
                dob, dod, ethnicity, tribal_affiliation,
                identifying_marks, aliases, occupation,
                gender_source, age_source, race_source
            )
            VALUES (
                :cid, :fn, :ln, :gender,
                :age_text, :race,
                NULL, NULL,
                NULL, NULL,
                NULL, NULL, NULL, NULL,
                NULL, NULL, NULL,
                CASE WHEN :gender IS NULL THEN NULL ELSE 'source' END,
                CASE WHEN :age_text IS NULL THEN NULL ELSE 'source' END,
                CASE WHEN :race IS NULL THEN NULL ELSE 'source' END
            )
        """),
        {
            "cid": case_id,
            "fn": first_name,
            "ln": last_name,
            "gender": gender,
            "age_text": age_text,
            "race": race,
        },
    )


def _insert_contact(session: Session, *, case_id: int, r: Row[Any]) -> None:
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :agency, :phone, NULL, NULL)
        """),
        {
            "cid": case_id,
            "agency": clean_sentinel(r.contact_agency),
            "phone": clean_sentinel(r.contact_phone),
        },
    )


def _insert_photo(
    session: Session,
    *,
    case_id: int,
    source_case_id: str,
    photo: dict[str, Any],
    is_primary: bool,
) -> None:
    filename = photo.get("filename")
    storage_path = (
        f"cold_case_ar_asp/{safe_filename(source_case_id)}/{filename}" if filename else None
    )
    session.execute(
        text("""
            INSERT INTO cold_case.case_photo
                (case_id, filename, content_type, alt_text, sha256, is_primary,
                 source_url, storage_path)
            VALUES (:cid, :filename, :ctype, :alt, :sha, :primary, :src, :storage_path)
        """),
        {
            "cid": case_id,
            "filename": filename,
            "ctype": photo.get("content_type"),
            "alt": photo.get("alt"),
            "sha": photo.get("sha256"),
            "primary": is_primary,
            "src": photo.get("source_url"),
            "storage_path": storage_path,
        },
    )

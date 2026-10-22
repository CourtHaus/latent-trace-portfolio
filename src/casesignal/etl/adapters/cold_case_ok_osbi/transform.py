"""Transform stage for the OK OSBI adapter."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_ok_osbi.county_fips import county_from_narrative
from casesignal.etl.adapters.cold_case_ok_osbi.county_fips import (
    name_for_fips as _county_name_for_fips,
)
from casesignal.etl.services.normalizers import clean_sentinel
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

_OK_STATE = "OK"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    """Bare name → url slug. (The shared build_case_slug also folds in
    city/state/year, so it's wrong for a name-only source_case_id anchor —
    a local slug is intentional here.)"""
    return _SLUG_RE.sub("-", value.lower()).strip("-")


_MONTH_YEAR_RE = re.compile(r"^(?P<month>[A-Za-z]+)\s+(?P<year>(?:19|20)\d{2})$")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})


def normalize_ok_date(raw: str | None) -> str | None:
    """OSBI dates → ISO. Formats seen: 'November 15, 1984', '08/27/1980',
    'December 2004' (month-year → day 01), 'Unknown' → None."""
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
            return (
                datetime.strptime(f"{m.group('month')} 1, {m.group('year')}", "%B %d, %Y")
                .date()
                .isoformat()
            )
        except ValueError:
            pass
    return None


def map_case_type(label: str | None) -> str:
    """OSBI type label → canonical case_type. Unknown → 'cold_case' (logged).

    Prefix/tolerant matching, because OSBI's own bold type line carries source
    typos and truncations: 'Suspicious Disappearanc' (missing the final 'e'),
    a bare 'H' for Homicide. Matching on a prefix rather than the exact string
    absorbs those and any similar variants on pages not captured as fixtures.
    """
    key = (label or "").strip().lower()
    if not key:
        return "cold_case"
    if key.startswith("homicide") or key == "h":
        return "homicide"
    if key.startswith("missing"):
        return "missing_person"
    if key.startswith("suspicious disappear"):
        return "missing_person"
    if key.startswith("suspicious death"):
        return "suspicious_death"
    logger.warning("OK OSBI: unknown case-type label %r -> cold_case", label)
    return "cold_case"


def parse_contact(text: str | None) -> tuple[str | None, str | None, str | None]:
    """(agency, email, phone) from the OSBI contact paragraph.

    Two shapes: '... contact the OSBI via email cold.case@osbi.ok.gov' and
    '... contact the Duncan PD Crime Stoppers, phone (580) 252-4636'.
    """
    value = clean_sentinel(text)
    if not value:
        return None, None, None
    email_m = _EMAIL_RE.search(value)
    phone_m = _PHONE_RE.search(value)
    email = email_m.group(0) if email_m else None
    phone = phone_m.group(0) if phone_m else None
    agency: str | None = None
    # agency = the noun phrase between 'contact ' and the email/phone/comma
    am = re.search(r"contact\s+(?:the\s+)?(.+?)(?:,|\s+via email|\s+phone|$)", value, re.I)
    if am:
        candidate = am.group(1).strip()
        # Don't let the agency capture swallow a phone number that appears
        # without a preceding comma/"phone" marker to delimit it (e.g.
        # "... Barnsdall Police Department at (918) 847-2285").
        if phone_m is not None and am.start(1) <= phone_m.start() < am.end(1):
            candidate = value[am.start(1) : phone_m.start()].strip()
        candidate = candidate.rstrip(" .,;:")
        if candidate and "@" not in candidate:
            agency = candidate
    return agency, email, phone


def assign_source_case_ids(entries: list[dict[str, Any]]) -> None:
    """Set entry['source_case_id'] = slug(name)[-date]. OSBI has no case
    number, so name + incident_date is the stable validation-gate anchor.
    Collisions (same name, same/absent date, or a suffix that happens to
    collide with another entry's base id) get a numeric suffix chosen
    against the set of FINAL ids already taken; a final pass asserts
    global uniqueness as a belt-and-suspenders check (should never fire)."""
    taken: set[str] = set()
    for e in entries:
        base = _slugify(e["name"])
        iso = e.get("incident_date_iso")
        sid = f"{base}-{iso}" if iso else base
        suffix = 1
        while sid in taken:
            suffix += 1
            sid = f"{base}-{iso}-{suffix}" if iso else f"{base}-{suffix}"
        taken.add(sid)
        e["source_case_id"] = sid
    seen: set[str] = set()
    for e in entries:
        if e["source_case_id"] in seen:
            raise ValueError(f"duplicate OK source_case_id: {e['source_case_id']!r}")
        seen.add(e["source_case_id"])


def _split_display_name(name: str | None) -> tuple[str, str]:
    """Display-order name ('James Middle Example') → (first_part, last).
    A generational suffix stays attached to the surname, whether it's
    comma-joined ('Felix Bailey, Jr.' → ('Felix', 'Bailey, Jr.')) or
    space-joined ('John Smith Jr' → ('John', 'Smith Jr'))."""
    parts = [p.strip() for p in (name or "").split() if p.strip()]
    if not parts:
        return "Unknown", ""
    if len(parts) == 1:
        return parts[0], ""
    if len(parts) >= 3 and parts[-1].rstrip(".").lower() in _NAME_SUFFIXES:
        return " ".join(parts[:-2]), f"{parts[-2]} {parts[-1]}"
    return " ".join(parts[:-1]), parts[-1]


_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_TIER2_PROMPT_HASH = compute_prompt_hash(load_tier2_v4_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()


def transform_ok(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")
    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_ok_osbi_dv{context.dataset_version_id}"
    cases_inserted = photos_inserted = extraction_jobs = geocoding_jobs = 0
    with_county = 0

    with session_factory() as session:
        try:
            _delete_existing_canonical_rows(session, dataset_version_id=context.dataset_version_id)
            raw_rows = session.execute(
                text(f"""
                    SELECT dataset_version_id, source_case_id, name, case_name, case_type,
                           date_text, incident_date_iso, narrative, contact_text,
                           source_range_url, photos_json
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                narrative = r.narrative or ""
                county_fips = county_from_narrative(narrative)
                if county_fips:
                    with_county += 1
                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=r.case_name,
                    case_type=r.case_type or "cold_case",
                    incident_date_iso=r.incident_date_iso,
                    county_fips=county_fips,
                    about_text=narrative,
                )
                cases_inserted += 1
                _insert_victim(session, case_id=case_id, case_name=r.case_name)
                _insert_contact(session, case_id=case_id, contact_text=r.contact_text)

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

                if county_fips:
                    address_text = f"{_county_name_for_fips(county_fips)} County, OK"
                else:
                    address_text = "Oklahoma"
                session.execute(
                    text("""
                        INSERT INTO cold_case.geocoding_job
                            (case_id, address_text, state_code, zip_code, county_fips)
                        VALUES (:cid, :addr, :state, NULL, :fips)
                    """),
                    {"cid": case_id, "addr": address_text, "state": _OK_STATE, "fips": county_fips},
                )
                geocoding_jobs += 1

            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("transform", cases_inserted)
    log = context.logger or logger
    log.info(
        "OK OSBI transform: %d cases (%d with county floor), %d photos, "
        "%d extraction jobs, %d geocoding jobs",
        cases_inserted, with_county, photos_inserted, extraction_jobs, geocoding_jobs,
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
    slug_base = build_case_slug(case_name=case_name, city=None, state=_OK_STATE, year=year)
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
                "state": _OK_STATE,
                "fips": county_fips,
                "date": incident_date_iso,
                "about": about_text,
            },
        ).scalar_one()
    )


def _insert_victim(session: Session, *, case_id: int, case_name: str | None) -> None:
    first_name, last_name = _split_display_name(clean_sentinel(case_name))
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
                :cid, :fn, :ln, NULL,
                NULL, NULL,
                NULL, NULL,
                NULL, NULL,
                NULL, NULL, NULL, NULL,
                NULL, NULL, NULL,
                NULL, NULL, NULL
            )
        """),
        {
            "cid": case_id,
            "fn": first_name,
            "ln": last_name,
        },
    )


def _insert_contact(session: Session, *, case_id: int, contact_text: str | None) -> None:
    agency, email, phone = parse_contact(contact_text)
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :agency, :phone, NULL, :email)
        """),
        {
            "cid": case_id,
            "agency": agency,
            "phone": phone,
            "email": email,
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
        f"cold_case_ok_osbi/{safe_filename(source_case_id)}/{filename}" if filename else None
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

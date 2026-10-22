"""Transform stage for the CO CBI adapter.

Reads raw_cold_case.cold_case_co_dv<N> and writes canonical model:
  - cold_case.cases (with new namus_case_id, ncmec_case_id columns)
  - cold_case.victim (with new dob, dod, ethnicity, tribal_affiliation,
    identifying_marks, aliases, occupation columns)
  - cold_case.case_photo — one row per photo, first marked is_primary=TRUE
  - cold_case.contact — agency-line shape (last_name=agency, address=city)
  - Tier-1 extraction job (weapon + location_type from narrative)
  - geocoding_job — directly enqueued (no Tier-2 for CO)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_co.county_fips import lookup as fips_lookup
from casesignal.etl.services.normalizers import (
    clean_sentinel as _clean_sentinel,
)
from casesignal.etl.services.normalizers import (
    normalize_date as _normalize_date,
)
from casesignal.etl.services.normalizers import (
    normalize_gender as _normalize_gender,
)
from casesignal.etl.services.normalizers import (
    try_int as _try_int,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
)
from casesignal.extraction.cold_case.queue_handler import enqueue_extraction_job
from casesignal.geocoding.address_extract import extract_address

logger = logging.getLogger(__name__)


_CO_STATE = "CO"

# Pin Tier-1 prompt at module load
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()


def transform_co(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_co_dv{context.dataset_version_id}"

    cases_inserted = 0
    photos_inserted = 0
    fips_missing = 0
    extraction_jobs = 0
    geocoding_jobs = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT detail_id, name, aliases, dob, dod, occupation, age, gender,
                           race, ethnicity, tribal_affiliation, height, weight,
                           eye_color, hair_color, identifying_marks,
                           case_type, case_status, incident_date,
                           agency, agency_case_id, judicial_district, city, county,
                           namus_case_id, ncmec_case_id, narrative,
                           photos_json, source_detail_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY detail_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                source_county_fips = fips_lookup(r.county)
                if source_county_fips is None:
                    fips_missing += 1

                # Composite source_case_id: agency_case_# alone can collide
                # across CO agencies (e.g., "98-38" exists at multiple
                # county sheriffs). Detail_id is globally unique per CBI.
                if r.agency_case_id:
                    composite_scid = f"{r.agency_case_id}-{r.detail_id}"
                else:
                    composite_scid = f"co-{r.detail_id}"

                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    detail_id=r.detail_id,
                    agency_case_id=composite_scid,
                    name=r.name,
                    incident_date_iso=_normalize_date(r.incident_date),
                    city=r.city,
                    source_county_fips=source_county_fips,
                    narrative=r.narrative or "",
                    namus_case_id=_clean_sentinel(r.namus_case_id),
                    ncmec_case_id=_clean_sentinel(r.ncmec_case_id),
                )
                cases_inserted += 1

                _insert_victim(session, case_id=case_id, r=r)
                _insert_contact(session, case_id=case_id, agency=r.agency, city=r.city)

                photo_meta = json.loads(r.photos_json) if r.photos_json else []
                for i, p in enumerate(photo_meta):
                    _insert_photo(
                        session,
                        case_id=case_id,
                        photo=p,
                        detail_id=r.detail_id,
                        is_primary=(i == 0),
                    )
                    photos_inserted += 1

                # Tier-1 only — no Tier-2 for CO (structured demographics cover what T2 would extract)
                enqueue_extraction_job(
                    session,
                    case_id=case_id,
                    prompt_hash=_TIER1_PROMPT_HASH,
                    model_id=_PINNED_MODEL_ID,
                    prompt_tier=1,
                )
                extraction_jobs += 1

                # Geocoding: try to extract a street-level address from the narrative
                # before falling back to city-level. Census street geocoder needs
                # an actual address; "Denver, CO" alone only yields county centroid.
                extracted = extract_address(r.narrative, city=r.city, state_code="CO")
                if extracted:
                    address_text = extracted
                elif r.city:
                    address_text = f"{r.city}, CO"
                else:
                    address_text = "Colorado"
                session.execute(
                    text("""
                        INSERT INTO cold_case.geocoding_job
                            (case_id, address_text, state_code, zip_code, county_fips)
                        VALUES (:cid, :addr, :state, NULL, :fips)
                    """),
                    {
                        "cid": case_id,
                        "addr": address_text,
                        "state": _CO_STATE,
                        "fips": source_county_fips,
                    },
                )
                geocoding_jobs += 1

            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("transform", cases_inserted)
    if context.logger is not None:
        context.logger.info(
            "CO transform: %d cases (%d w/o county FIPS), %d photos, "
            "%d Tier-1 jobs, %d geocoding jobs",
            cases_inserted,
            fips_missing,
            photos_inserted,
            extraction_jobs,
            geocoding_jobs,
        )


def _insert_case(
    session: Session,
    *,
    dataset_version_id: int,
    detail_id: int,
    agency_case_id: str,
    name: str,
    incident_date_iso: str | None,
    city: str | None,
    source_county_fips: str | None,
    narrative: str,
    namus_case_id: str | None,
    ncmec_case_id: str | None,
) -> int:
    year = None
    if incident_date_iso and len(incident_date_iso) >= 4:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None

    slug_base = build_case_slug(case_name=name, city=city, state=_CO_STATE, year=year)
    slug = resolve_slug_collision(session, slug_base)

    return int(
        session.execute(
            text("""
            INSERT INTO cold_case.cases (
                dataset_version_id, source_case_id, slug,
                case_name, case_type, state, city, source_county_fips,
                incident_date, address,
                about_text, latitude, longitude, geocode_precision,
                namus_case_id, ncmec_case_id,
                incident_date_source
            )
            VALUES (
                :dv, :scid, :slug,
                :name, 'homicide', :state, :city, :fips,
                :date, NULL,
                :about, NULL, NULL, NULL,
                :namus, :ncmec,
                CASE WHEN :date IS NULL THEN NULL ELSE 'source' END
            )
            RETURNING case_id
        """),
            {
                "dv": dataset_version_id,
                "scid": agency_case_id,
                "slug": slug,
                "name": name,
                "state": _CO_STATE,
                "city": city,
                "fips": source_county_fips,
                "date": incident_date_iso,
                "about": narrative,
                "namus": namus_case_id,
                "ncmec": ncmec_case_id,
            },
        ).scalar_one()
    )


def _insert_victim(session: Session, *, case_id: int, r: Row[Any]) -> None:
    """Populate all victim columns including the new 7 from migration 0004."""
    parts = [p.strip() for p in (r.name or "").split() if p.strip()]
    if not parts:
        first, last = "Unknown", ""
    elif len(parts) == 1:
        first, last = parts[0], ""
    else:
        last = parts[-1]
        first = " ".join(parts[:-1])

    gender = _normalize_gender(r.gender)
    # age_num is a GENERATED column on cold_case.victim — Postgres computes it
    # from age_text. Don't insert it directly.
    weight_num = _try_int(_strip_unit(r.weight, "lbs"))

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
                :height, :weight,
                :eye, :hair,
                :dob, :dod, :eth, :tribal,
                :marks, :aliases, :occupation,
                CASE WHEN :gender IS NULL THEN NULL ELSE 'source' END,
                CASE WHEN :age_text IS NULL THEN NULL ELSE 'source' END,
                CASE WHEN :race IS NULL THEN NULL ELSE 'source' END
            )
        """),
        {
            "cid": case_id,
            "fn": first,
            "ln": last,
            "gender": gender,
            "age_text": _clean_sentinel(r.age),
            "race": _clean_sentinel(r.race),
            "height": _clean_sentinel(r.height),
            "weight": weight_num,
            "eye": _clean_sentinel(r.eye_color),
            "hair": _clean_sentinel(r.hair_color),
            "dob": _clean_sentinel(r.dob),
            "dod": _clean_sentinel(r.dod),
            "eth": _clean_sentinel(r.ethnicity),
            "tribal": _clean_sentinel(r.tribal_affiliation),
            "marks": _clean_sentinel(r.identifying_marks),
            "aliases": _clean_sentinel(r.aliases),
            "occupation": _clean_sentinel(r.occupation),
        },
    )


def _insert_contact(
    session: Session,
    *,
    case_id: int,
    agency: str | None,
    city: str | None,
) -> None:
    """Same shape as DC fallback: agency name in last_name, city in address."""
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :ln, NULL, :addr, NULL)
        """),
        {"cid": case_id, "ln": agency, "addr": city},
    )


def _insert_photo(
    session: Session,
    *,
    case_id: int,
    photo: dict[str, Any],
    detail_id: int,
    is_primary: bool,
) -> None:
    filename = photo.get("filename")
    storage_path = f"cold_case_co/{detail_id}/{filename}" if filename else None
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
            "alt": photo.get("alt_text"),
            "sha": photo.get("sha256"),
            "primary": is_primary,
            "src": photo.get("source_url"),
            "storage_path": storage_path,
        },
    )


def _strip_unit(raw: str | None, unit: str) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    if s.lower().endswith(unit.lower()):
        s = s[: -len(unit)].strip()
    return s

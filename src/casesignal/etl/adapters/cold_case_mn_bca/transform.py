"""Transform stage for the MN BCA adapter.

Reads raw_cold_case.cold_case_mn_bca_dv<N> and writes the canonical model:
  - cold_case.cases -- case_type='homicide'; incident_date from the harvest
    (incident_date_source='source'); address NULL (Tier-2 fills via the
    closed loop); about_text = the SOC PDF narrative.
  - cold_case.victim -- age from the harvest (age_source='source');
    gender/race from the PDF when it carried clean single-token values
    (*_source='source'), else NULL for Tier-2 to fill.
  - cold_case.case_photo -- one row per fetched photo, is_primary=TRUE.
  - cold_case.contact -- per-case agency + phone from the PDF closing line,
    falling back to the statewide BCA constant.
  - extraction_job -- Tier-1 + Tier-2 per case.
  - geocoding_job -- initial city/county baseline; Tier-2 upgrades it to a
    street/landmark fix via the closed loop if it extracts an address.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_mn_bca.county_fips import lookup as mn_fips
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

_MN_STATE = "MN"

_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_TIER2_PROMPT_HASH = compute_prompt_hash(load_tier2_v4_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()

# Statewide fallback when a SOC PDF yields no contact line.
_BCA_CONTACT_AGENCY = "Minnesota Bureau of Criminal Apprehension"
_BCA_CONTACT_PHONE = "1-877-996-6222"  # BCA tip line, verified in SOC PDF footers


def transform_mn(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_mn_bca_dv{context.dataset_version_id}"

    cases_inserted = 0
    photos_inserted = 0
    fips_missing = 0
    extraction_jobs = 0
    geocoding_jobs = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT source_case_id,
                           name_first, name_middle, name_last, name_suffix,
                           age, incident_date, date_of_birth,
                           location_city, location_county,
                           narrative, pdf_sex, pdf_race,
                           contact_agency, contact_phone,
                           photo_filename, photo_content_type,
                           photo_sha256, photo_source_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                county = clean_sentinel(r.location_county)
                city = clean_sentinel(r.location_city)
                source_county_fips = mn_fips(county)
                if source_county_fips is None:
                    fips_missing += 1

                case_name = _build_case_name(r)
                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=case_name,
                    city=city,
                    source_county_fips=source_county_fips,
                    incident_date_iso=r.incident_date,
                    narrative=r.narrative or "",
                )
                cases_inserted += 1

                _insert_victim(session, case_id=case_id, r=r)
                _insert_contact(session, case_id=case_id, r=r)

                if r.photo_filename:
                    _insert_photo(session, case_id=case_id, r=r)
                    photos_inserted += 1

                enqueue_extraction_job(
                    session,
                    case_id=case_id,
                    prompt_hash=_TIER1_PROMPT_HASH,
                    model_id=_PINNED_MODEL_ID,
                    prompt_tier=1,
                )
                enqueue_extraction_job(
                    session,
                    case_id=case_id,
                    prompt_hash=_TIER2_PROMPT_HASH,
                    model_id=_PINNED_MODEL_ID,
                    prompt_tier=2,
                )
                extraction_jobs += 2

                if city:
                    address_text = f"{city}, MN"
                elif county:
                    address_text = f"{county} County, MN"
                else:
                    address_text = "Minnesota"
                session.execute(
                    text("""
                        INSERT INTO cold_case.geocoding_job
                            (case_id, address_text, state_code, zip_code, county_fips)
                        VALUES (:cid, :addr, :state, NULL, :fips)
                    """),
                    {
                        "cid": case_id,
                        "addr": address_text,
                        "state": _MN_STATE,
                        "fips": source_county_fips,
                    },
                )
                geocoding_jobs += 1

            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("transform", cases_inserted)
    log = context.logger or logger
    log.info(
        "MN transform: %d cases (%d w/o county FIPS), %d photos, "
        "%d extraction jobs (T1+T2), %d geocoding jobs",
        cases_inserted,
        fips_missing,
        photos_inserted,
        extraction_jobs,
        geocoding_jobs,
    )


def _build_case_name(r: Row[Any]) -> str:
    parts = [
        clean_sentinel(r.name_first),
        clean_sentinel(r.name_middle),
        clean_sentinel(r.name_last),
        clean_sentinel(r.name_suffix),
    ]
    name = " ".join(p for p in parts if p)
    return name or f"case-{r.source_case_id}"


def _insert_case(
    session: Session,
    *,
    dataset_version_id: int,
    source_case_id: str,
    case_name: str,
    city: str | None,
    source_county_fips: str | None,
    incident_date_iso: str | None,
    narrative: str,
) -> int:
    year: int | None = None
    if incident_date_iso and len(incident_date_iso) >= 4:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None

    slug_base = build_case_slug(case_name=case_name, city=city, state=_MN_STATE, year=year)
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
                    :name, 'homicide', :state, :city, :fips,
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
                "state": _MN_STATE,
                "city": city,
                "fips": source_county_fips,
                "date": incident_date_iso,
                "about": narrative,
            },
        ).scalar_one()
    )


def _insert_victim(session: Session, *, case_id: int, r: Row[Any]) -> None:
    first_parts = [clean_sentinel(r.name_first), clean_sentinel(r.name_middle)]
    first = " ".join(p for p in first_parts if p) or "Unknown"
    last_parts = [clean_sentinel(r.name_last), clean_sentinel(r.name_suffix)]
    last = " ".join(p for p in last_parts if p)

    gender = normalize_gender(r.pdf_sex)
    race = clean_sentinel(r.pdf_race)
    age_text = clean_sentinel(r.age)
    dob = clean_sentinel(r.date_of_birth)

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
                :age, :race,
                NULL, NULL,
                NULL, NULL,
                :dob, NULL, NULL, NULL,
                NULL, NULL, NULL,
                CASE WHEN :gender IS NULL THEN NULL ELSE 'source' END,
                CASE WHEN :age IS NULL THEN NULL ELSE 'source' END,
                CASE WHEN :race IS NULL THEN NULL ELSE 'source' END
            )
        """),
        {
            "cid": case_id,
            "fn": first,
            "ln": last,
            "gender": gender,
            "age": age_text,
            "race": race,
            "dob": dob,
        },
    )


def _insert_contact(session: Session, *, case_id: int, r: Row[Any]) -> None:
    """Per-case contact from the SOC PDF, falling back to the BCA tip line."""
    agency = clean_sentinel(r.contact_agency) or _BCA_CONTACT_AGENCY
    phone = clean_sentinel(r.contact_phone) or _BCA_CONTACT_PHONE
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :ln, :phone, NULL, NULL)
        """),
        {"cid": case_id, "ln": agency, "phone": phone},
    )


def _insert_photo(session: Session, *, case_id: int, r: Row[Any]) -> None:
    storage_path = (
        f"cold_case_mn_bca/{safe_filename(r.source_case_id)}/{r.photo_filename}"
    )
    session.execute(
        text("""
            INSERT INTO cold_case.case_photo
                (case_id, filename, content_type, alt_text, sha256, is_primary,
                 source_url, storage_path)
            VALUES (:cid, :filename, :ctype, NULL, :sha, TRUE, :src, :storage_path)
        """),
        {
            "cid": case_id,
            "filename": r.photo_filename,
            "ctype": r.photo_content_type,
            "sha": r.photo_sha256,
            "src": r.photo_source_url,
            "storage_path": storage_path,
        },
    )

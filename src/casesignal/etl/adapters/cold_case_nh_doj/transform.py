"""Transform stage for the NH DOJ adapter.

Reads raw_cold_case.cold_case_nh_doj_dv<N> and writes canonical model:
  - cold_case.cases (with case_type from API category — homicide or
    suspicious_death; provenance for incident_date/address NULL on insert,
    Tier-2 will fill via closed-loop helper)
  - cold_case.victim (age from API tag with age_source='source';
    first/last/gender deferred to Tier-2)
  - cold_case.case_photo — one row per non-placeholder photo
  - cold_case.contact — single state-wide DOJ row reused per case
  - Tier-1 + Tier-2 extraction jobs enqueued
  - cold_case.geocoding_job — initial city/state baseline; Tier-2 will
    upgrade via closed-loop helper if it extracts a street address.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_nh_doj.county_fips import lookup as nh_fips
from casesignal.etl.services.normalizers import split_victim_name as _split_victim_name
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
    load_tier2_v4_prompt_template,
)
from casesignal.extraction.cold_case.queue_handler import enqueue_extraction_job

logger = logging.getLogger(__name__)

_NH_STATE = "NH"

# Pinned at module load — every transform run uses a consistent
# (prompt_hash, model_id, tier) tuple.
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_TIER2_PROMPT_HASH = compute_prompt_hash(load_tier2_v4_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()

# Map API category → cases.case_type value.
_CASE_TYPE_BY_CATEGORY: dict[str, str] = {
    "Unsolved Homicide": "homicide",
    "Suspicious Death": "suspicious_death",
}

# NH DOJ contact — published on the CCU landing page; reused per case.
_NH_CONTACT_AGENCY = "New Hampshire Department of Justice — Cold Case Unit"
_NH_CONTACT_PHONE = "(603) 271-3658"
_NH_CONTACT_ADDRESS = "1 Granite Place South, Concord, NH 03301"

# `Lastname, Firstname` -> `Firstname Lastname`
_TITLE_COMMA_RE = re.compile(r"^([^,]+),\s*(.+)$")


def _flip_title(title: str) -> str:
    m = _TITLE_COMMA_RE.match(title.strip())
    if not m:
        return title.strip()
    return f"{m.group(2).strip()} {m.group(1).strip()}"


def transform_nh(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_nh_doj_dv{context.dataset_version_id}"

    cases_inserted = 0
    photos_inserted = 0
    fips_missing = 0
    extraction_jobs = 0
    geocoding_jobs = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT dataset_version_id,
                           source_case_id, title, slug, category_label,
                           year_tag, town_tag, age_tag,
                           narrative,
                           photo_filename, photo_content_type, photo_alt_text,
                           photo_sha256, photo_source_url,
                           source_detail_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                case_type = _CASE_TYPE_BY_CATEGORY.get(r.category_label, "homicide")
                city = r.town_tag.title() if r.town_tag else None
                source_county_fips = nh_fips(r.town_tag)
                if source_county_fips is None:
                    fips_missing += 1
                case_name = _flip_title(r.title)

                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=case_name,
                    case_type=case_type,
                    city=city,
                    source_county_fips=source_county_fips,
                    narrative=r.narrative or "",
                    year_tag=r.year_tag,
                )
                cases_inserted += 1

                _insert_victim(session, case_id=case_id, case_name=case_name, age_tag=r.age_tag)
                _insert_contact(session, case_id=case_id)

                if r.photo_filename:
                    _insert_photo(session, case_id=case_id, r=r)
                    photos_inserted += 1

                # Tier-1 + Tier-2 extraction jobs
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

                # Initial city/state geocoding — Tier-2 may upgrade later.
                if city:
                    address_text = f"{city}, NH"
                else:
                    address_text = "New Hampshire"
                session.execute(
                    text("""
                        INSERT INTO cold_case.geocoding_job
                            (case_id, address_text, state_code, zip_code, county_fips)
                        VALUES (:cid, :addr, :state, NULL, :fips)
                    """),
                    {
                        "cid": case_id,
                        "addr": address_text,
                        "state": _NH_STATE,
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
            "NH transform: %d cases (%d w/o county FIPS), %d photos, "
            "%d extraction jobs (T1+T2), %d geocoding jobs",
            cases_inserted, fips_missing, photos_inserted,
            extraction_jobs, geocoding_jobs,
        )


def _insert_case(
    session: Session,
    *,
    dataset_version_id: int,
    source_case_id: str,
    case_name: str,
    case_type: str,
    city: str | None,
    source_county_fips: str | None,
    narrative: str,
    year_tag: str | None,
) -> int:
    year: int | None = None
    if year_tag:
        try:
            year = int(year_tag)
        except ValueError:
            year = None

    slug_base = build_case_slug(case_name=case_name, city=city, state=_NH_STATE, year=year)
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
                    :name, :ctype, :state, :city, :fips,
                    NULL, NULL,
                    :about, NULL, NULL, NULL,
                    NULL, NULL
                )
                RETURNING case_id
            """),
            {
                "dv": dataset_version_id,
                "scid": source_case_id,
                "slug": slug,
                "name": case_name,
                "ctype": case_type,
                "state": _NH_STATE,
                "city": city,
                "fips": source_county_fips,
                "about": narrative,
            },
        ).scalar_one()
    )


def _insert_victim(
    session: Session,
    *,
    case_id: int,
    case_name: str,
    age_tag: str | None,
) -> None:
    first, last = _split_victim_name(case_name)
    age_text: str | None = age_tag.strip() if age_tag else None
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
                :age, NULL,
                NULL, NULL,
                NULL, NULL,
                NULL, NULL, NULL, NULL,
                NULL, NULL, NULL,
                NULL,
                CASE WHEN :age IS NULL THEN NULL ELSE 'source' END,
                NULL
            )
        """),
        {"cid": case_id, "fn": first, "ln": last, "age": age_text},
    )


def _insert_contact(session: Session, *, case_id: int) -> None:
    session.execute(
        text("""
            INSERT INTO cold_case.contact
                (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :ln, :phone, :addr, NULL)
        """),
        {
            "cid": case_id,
            "ln": _NH_CONTACT_AGENCY,
            "phone": _NH_CONTACT_PHONE,
            "addr": _NH_CONTACT_ADDRESS,
        },
    )


def _insert_photo(session: Session, *, case_id: int, r: Row[Any]) -> None:
    storage_path = (
        f"cold_case_nh_doj/{r.source_case_id}/{r.photo_filename}"
    )
    session.execute(
        text("""
            INSERT INTO cold_case.case_photo
                (case_id, filename, content_type, alt_text, sha256,
                 is_primary, source_url, storage_path)
            VALUES (:cid, :filename, :ctype, :alt, :sha, TRUE, :src, :storage_path)
        """),
        {
            "cid": case_id,
            "filename": r.photo_filename,
            "ctype": r.photo_content_type,
            "alt": r.photo_alt_text,
            "sha": r.photo_sha256,
            "src": r.photo_source_url,
            "storage_path": storage_path,
        },
    )

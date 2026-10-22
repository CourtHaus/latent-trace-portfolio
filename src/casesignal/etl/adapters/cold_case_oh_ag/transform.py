"""Transform stage for the OH AG adapter.

Reads raw_cold_case.cold_case_oh_ag_dv<N> and writes canonical model:
  - cold_case.cases (with incident_date_source + address_source provenance)
  - cold_case.victim (with gender_source + race_source per PR #70 contract)
  - cold_case.case_photo — one row per photo, first marked is_primary=TRUE
  - cold_case.contact — agency-line shape (last_name=agency, address=city)
  - Tier-1 extraction job (weapon + location_type from narrative)
  - geocoding_job — directly enqueued (no Tier-2; OH publishes structured demographics)

Mirrors cold_case_co/transform.py post-PR-#70. All *_source columns set to
'source' when the value is non-null, per provenance contract.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_oh_ag.county_fips import lookup as oh_fips
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
from casesignal.etl.services.photo_helpers import safe_filename as _safe_filename
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
)
from casesignal.extraction.cold_case.queue_handler import enqueue_extraction_job

logger = logging.getLogger(__name__)

_OH_STATE = "OH"

# Pin Tier-1 prompt at module load (mirror CO/UT pattern)
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()


def transform_oh(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_oh_ag_dv{context.dataset_version_id}"

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
                           case_number, name, aliases, dob,
                           gender, race, height, weight_lbs,
                           hair_color, eye_color,
                           incident_date, address, city, county, agency,
                           narrative, photos_json, source_detail_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_detail_url
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                county = _clean_sentinel(r.county)
                city = _clean_sentinel(r.city)
                source_county_fips = oh_fips(county)
                if source_county_fips is None:
                    fips_missing += 1

                # Build source_case_id as composite `case_number-url_slug` —
                # OH AG's case_number is NOT globally unique (verified on the
                # 2026-05-13 ingest: case_numbers "1949" and "3441" each
                # appear twice; 5 cases have NULL case_number entirely).
                # URL slugs ARE unique (AG appends `-N` for collisions like
                # `Ball-2`, `Johnson-21`), so the composite is guaranteed
                # unique while preserving case_number visibility for users
                # who search by it.
                raw_case_number = _clean_sentinel(r.case_number)
                url_slug = r.source_detail_url.rsplit("/", 1)[-1]
                if raw_case_number:
                    source_case_id = f"{raw_case_number}-{url_slug}"
                else:
                    source_case_id = f"oh-{url_slug}"

                name = _clean_sentinel(r.name) or f"case-{source_case_id}"
                incident_date_iso = _normalize_date(r.incident_date)

                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=source_case_id,
                    name=name,
                    incident_date_iso=incident_date_iso,
                    address=_clean_sentinel(r.address),
                    city=city,
                    source_county_fips=source_county_fips,
                    narrative=r.narrative or "",
                )
                cases_inserted += 1

                _insert_victim(session, case_id=case_id, r=r)
                _insert_contact(session, case_id=case_id, agency=r.agency, city=city)

                photo_meta = json.loads(r.photos_json) if r.photos_json else []
                # Derive the on-disk subdir the same way raw_load does:
                # safe_filename(case_number) or safe_filename(url_slug)
                photo_subdir = _safe_filename(
                    _clean_sentinel(r.case_number) or url_slug
                )
                for i, p in enumerate(photo_meta):
                    _insert_photo(
                        session,
                        case_id=case_id,
                        photo=p,
                        photo_subdir=photo_subdir,
                        is_primary=(i == 0),
                    )
                    photos_inserted += 1

                # Tier-1 only — no Tier-2 for OH (structured demographics cover
                # what Tier-2 would extract).
                enqueue_extraction_job(
                    session,
                    case_id=case_id,
                    prompt_hash=_TIER1_PROMPT_HASH,
                    model_id=_PINNED_MODEL_ID,
                    prompt_tier=1,
                )
                extraction_jobs += 1

                # Geocoding: OH publishes a structured address field; use it directly
                # when available. Fall back to city-level, then state-level.
                addr_text = _clean_sentinel(r.address)
                if addr_text and city:
                    address_text = f"{addr_text}, {city}, OH"
                elif addr_text:
                    address_text = f"{addr_text}, OH"
                elif city:
                    address_text = f"{city}, OH"
                else:
                    address_text = "Ohio"
                session.execute(
                    text("""
                        INSERT INTO cold_case.geocoding_job
                            (case_id, address_text, state_code, zip_code, county_fips)
                        VALUES (:cid, :addr, :state, NULL, :fips)
                    """),
                    {
                        "cid": case_id,
                        "addr": address_text,
                        "state": _OH_STATE,
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
            "OH transform: %d cases (%d w/o county FIPS), %d photos, "
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
    source_case_id: str,
    name: str,
    incident_date_iso: str | None,
    address: str | None,
    city: str | None,
    source_county_fips: str | None,
    narrative: str,
) -> int:
    year = None
    if incident_date_iso and len(incident_date_iso) >= 4:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None

    slug_base = build_case_slug(case_name=name, city=city, state=_OH_STATE, year=year)
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
                :date, :addr,
                :about, NULL, NULL, NULL,
                CASE WHEN :date IS NULL THEN NULL ELSE 'source' END,
                CASE WHEN :addr IS NULL THEN NULL ELSE 'source' END
            )
            RETURNING case_id
        """),
            {
                "dv": dataset_version_id,
                "scid": source_case_id,
                "slug": slug,
                "name": name,
                "state": _OH_STATE,
                "city": city,
                "fips": source_county_fips,
                "date": incident_date_iso,
                "addr": address,
                "about": narrative,
            },
        ).scalar_one()
    )


def _insert_victim(session: Session, *, case_id: int, r: Row[Any]) -> None:
    parts = [p.strip() for p in (r.name or "").split() if p.strip()]
    if not parts:
        first, last = "Unknown", ""
    elif len(parts) == 1:
        first, last = parts[0], ""
    else:
        last = parts[-1]
        first = " ".join(parts[:-1])

    gender = _normalize_gender(r.gender)
    # weight_lbs is stored as INTEGER in the raw table — no unit stripping needed
    weight_num = _try_int(r.weight_lbs)

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
                NULL, :race,
                :height, :weight,
                :eye, :hair,
                :dob, NULL, NULL, NULL,
                NULL, :aliases, NULL,
                CASE WHEN :gender IS NULL THEN NULL ELSE 'source' END,
                NULL,
                CASE WHEN :race IS NULL THEN NULL ELSE 'source' END
            )
        """),
        {
            "cid": case_id,
            "fn": first,
            "ln": last,
            "gender": gender,
            "race": _clean_sentinel(r.race),
            "height": _clean_sentinel(r.height),
            "weight": weight_num,
            "eye": _clean_sentinel(r.eye_color),
            "hair": _clean_sentinel(r.hair_color),
            "dob": _clean_sentinel(r.dob),
            "aliases": _clean_sentinel(r.aliases),
        },
    )


def _insert_contact(
    session: Session,
    *,
    case_id: int,
    agency: str | None,
    city: str | None,
) -> None:
    """Agency-line shape: agency name in last_name, city in address. Mirrors CO."""
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :ln, NULL, :addr, NULL)
        """),
        {"cid": case_id, "ln": _clean_sentinel(agency), "addr": city},
    )


def _insert_photo(
    session: Session,
    *,
    case_id: int,
    photo: dict[str, Any],
    photo_subdir: str,
    is_primary: bool,
) -> None:
    # raw_load stores photos_json with key 'alt' (not 'alt_text')
    filename = photo.get("filename")
    storage_path = f"cold_case_oh_ag/{photo_subdir}/{filename}" if filename else None
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

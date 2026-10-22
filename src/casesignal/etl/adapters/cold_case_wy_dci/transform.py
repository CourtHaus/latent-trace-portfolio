"""Transform stage for the WY DCI adapter.

Reads raw_cold_case.cold_case_wy_dci_dv<N> and writes canonical model:
  - cold_case.cases (with incident_date_source + address_source provenance)
  - cold_case.victim (with gender_source + race_source + age_source per
    PR #70 contract; demographics come from structured CSV columns)
  - cold_case.contact — agency-line shape (last_name='Wyoming DCI', address=city)
  - cold_case.case_photo — one row per case with a non-empty `photo_filename`;
    bytes are copied from data/raw/.../photos/ into data/photos/cold_case_wy_dci/
  - cold_case.case_extractions — ONE synthetic row per case marking
    weapon + location_type as 'source'-derived MO (no LLM call).
    This is the WY signal: a structured-MO source is materialized
    directly into the Tier-1 extractions table so downstream
    consumers (filters, correlation) see it identically to LLM-derived MO.
  - cold_case.geocoding_job — directly enqueued (no Tier-2; WY publishes
    structured demographics + composed address).

Mirrors cold_case_oh_ag/transform.py shape — same session-factory / try /
rollback / commit pattern, with three WY-specific differences:
  1. No enqueue_extraction_job call — synthetic case_extractions row instead
  2. Photo source is local filesystem (not HTTP-fetched in raw_load)
  3. Slugs derive from victim_name (or 'Unidentified' fallback)
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_wy_dci.county_fips import lookup as wy_fips
from casesignal.etl.services.normalizers import (
    normalize_gender as _normalize_gender,
)
from casesignal.etl.services.normalizers import (
    split_victim_name as _split_victim_name,
)
from casesignal.etl.services.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

_WY_STATE = "WY"

# Photo copy paths — raw source lives under the dated raw dir, canonical
# destination is keyed by source_case_id (so multiple photos per case in a
# future extract land in distinct subdirs).
PHOTO_SRC_DIR = Path("data/raw/cold_case_wy_dci/2026-05-13/photos")
PHOTO_DST_ROOT = Path("data/photos/cold_case_wy_dci")


# --- MO normalization maps -------------------------------------------------
# These translate WY's structured weapon/scene_type vocabulary into the
# canonical MO enum values already used by the LLM-derived Tier-1 extractions
# (see check constraints on cold_case.case_extractions). Unknown / blank
# both collapse to 'unknown'.

_WEAPON_MAP: dict[str, str] = {
    "Firearm - other/unknown": "firearm",
    "Handgun": "firearm",
    "Rifle": "firearm",
    "Shotgun": "firearm",
    "Knife": "knife",
    "Blunt Object": "blunt",
    "Hands/ Fists/ Feet/ Body": "personal",
    "Rope or similar": "asphyxiation",
    "Other": "other",
    "Unknown": "unknown",
    "": "unknown",
}

_LOCATION_TYPE_MAP: dict[str, str] = {
    "Home": "residence",
    "Business": "commercial",
    "Bar/Restaurant": "commercial",
    "Highway/Road": "public_outdoor",
    "Automobile": "vehicle",
    "Automobile, Highway/Road": "public_outdoor",
    "Highway/Road, Parking Lot": "public_outdoor",
    "Parking Lot": "public_outdoor",
    "Desert": "public_outdoor",
    "Woods": "public_outdoor",
    "Park/Outdoor Recreation Area": "public_outdoor",
    "Unknown": "unknown",
    "": "unknown",
}


def normalize_weapon(raw: str | None) -> str:
    return _WEAPON_MAP.get((raw or "").strip(), "unknown")


def normalize_location_type(raw: str | None) -> str:
    return _LOCATION_TYPE_MAP.get((raw or "").strip(), "unknown")


# --- transform entrypoint --------------------------------------------------


def transform_wy(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_wy_dci_dv{context.dataset_version_id}"

    cases_inserted = 0
    photos_inserted = 0
    photos_missing = 0
    fips_missing = 0
    synthetic_extractions = 0
    geocoding_jobs = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT dataset_version_id,
                           source_case_id, reported_date, crime_types, weapon,
                           victim_name, victim_age, victim_sex, victim_race,
                           scene_type, scene_address, scene_business_name,
                           scene_city, scene_county, synopsis, photo_filename
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                county = _clean(r.scene_county)
                city = _clean(r.scene_city)
                scene_address = _clean(r.scene_address)
                source_county_fips = wy_fips(county)
                if source_county_fips is None and county:
                    fips_missing += 1

                victim_name = _clean(r.victim_name)
                case_name = victim_name or "Unidentified"
                incident_date_iso = _clean(r.reported_date)  # already ISO

                composed_address = _compose_address(scene_address, city)

                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=case_name,
                    incident_date_iso=incident_date_iso,
                    address=composed_address,
                    city=city,
                    source_county_fips=source_county_fips,
                    about_text=_clean(r.synopsis) or "",
                )
                cases_inserted += 1

                _insert_victim(
                    session,
                    case_id=case_id,
                    victim_name=victim_name,
                    victim_age=_clean(r.victim_age),
                    victim_sex=_clean(r.victim_sex),
                    victim_race=_clean(r.victim_race),
                )

                _insert_contact(session, case_id=case_id, city=city)

                photo_filename = _clean(r.photo_filename)
                if photo_filename:
                    inserted = _copy_and_insert_photo(
                        session,
                        case_id=case_id,
                        source_case_id=r.source_case_id,
                        photo_filename=photo_filename,
                    )
                    if inserted:
                        photos_inserted += 1
                    else:
                        photos_missing += 1

                _insert_synthetic_extraction(
                    session,
                    case_id=case_id,
                    weapon=normalize_weapon(r.weapon),
                    location_type=normalize_location_type(r.scene_type),
                )
                synthetic_extractions += 1

                _enqueue_geocoding(
                    session,
                    case_id=case_id,
                    address_text=composed_address,
                    source_county_fips=source_county_fips,
                )
                geocoding_jobs += 1

            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("transform", cases_inserted)
    if context.logger is not None:
        context.logger.info(
            "WY transform: %d cases (%d w/o county FIPS), %d photos inserted "
            "(%d source files missing), %d synthetic extractions, %d geocoding jobs",
            cases_inserted,
            fips_missing,
            photos_inserted,
            photos_missing,
            synthetic_extractions,
            geocoding_jobs,
        )


# --- per-row helpers -------------------------------------------------------


def _insert_case(
    session: Session,
    *,
    dataset_version_id: int,
    source_case_id: str,
    case_name: str,
    incident_date_iso: str | None,
    address: str | None,
    city: str | None,
    source_county_fips: str | None,
    about_text: str,
) -> int:
    year: int | None = None
    if incident_date_iso and len(incident_date_iso) >= 4:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None

    slug_base = build_case_slug(case_name=case_name, city=city, state=_WY_STATE, year=year)
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
                "name": case_name,
                "state": _WY_STATE,
                "city": city,
                "fips": source_county_fips,
                "date": incident_date_iso,
                "addr": address,
                "about": about_text,
            },
        ).scalar_one()
    )


def _insert_victim(
    session: Session,
    *,
    case_id: int,
    victim_name: str | None,
    victim_age: str | None,
    victim_sex: str | None,
    victim_race: str | None,
) -> None:
    first, last = _split_victim_name(victim_name)
    gender = _normalize_gender(victim_sex)
    # Race comes through verbatim — PR #79 race filter is case-insensitive
    # and WY's vocabulary (White, Black, American Indian, etc.) matches the
    # canonical labels other states use.
    race = victim_race or None
    age_text = victim_age or None

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
                NULL, NULL, NULL, NULL,
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
        },
    )


def _insert_contact(session: Session, *, case_id: int, city: str | None) -> None:
    """Agency-line contact: last_name = agency, address = city.

    WY DCI is the statewide registrar; the originating local agency is not
    consistently exposed in the source data, so we attribute to DCI uniformly
    (Q1 spec decision).
    """
    session.execute(
        text("""
            INSERT INTO cold_case.contact (
                case_id, first_name, last_name, phone, address, email
            )
            VALUES (:cid, NULL, :ln, NULL, :addr, NULL)
        """),
        {
            "cid": case_id,
            "ln": "Wyoming Division of Criminal Investigation",
            "addr": city,
        },
    )


def _copy_and_insert_photo(
    session: Session,
    *,
    case_id: int,
    source_case_id: str,
    photo_filename: str,
) -> bool:
    """Copy photo bytes from the raw dir to the canonical dir, then insert
    the case_photo row. Returns True if the file was found + inserted.

    Source filename is preserved verbatim (e.g. wy-2018-02-03-bruegger.jpg);
    only the parent directory changes.
    """
    src = PHOTO_SRC_DIR / photo_filename
    if not src.exists():
        logger.warning("WY photo source missing for case '%s': %s", source_case_id, src)
        return False

    dst_dir = PHOTO_DST_ROOT / source_case_id
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / photo_filename

    # shutil.copy2 preserves mtime; copyfile is enough but copy2 mirrors the
    # behavior other adapters use when persisting fetched bytes.
    shutil.copy2(src, dst)

    sha256 = hashlib.sha256(dst.read_bytes()).hexdigest()

    storage_path = f"cold_case_wy_dci/{source_case_id}/{photo_filename}"
    session.execute(
        text("""
            INSERT INTO cold_case.case_photo (
                case_id, filename, content_type, alt_text,
                sha256, is_primary, source_url, storage_path
            )
            VALUES (:cid, :filename, :ctype, NULL, :sha, TRUE, NULL, :storage_path)
        """),
        {
            "cid": case_id,
            "filename": photo_filename,
            "ctype": "image/jpeg",
            "sha": sha256,
            "storage_path": storage_path,
        },
    )
    return True


def _insert_synthetic_extraction(
    session: Session,
    *,
    case_id: int,
    weapon: str,
    location_type: str,
) -> None:
    """Insert a Tier-1 case_extractions row marking MO as source-derived.

    Locked field values per Phase 6 spec:
      prompt_tier=1, model_id='source', prompt_hash='source-v1',
      extractor_version='SOURCE'.

    All Tier-2-only fields (incident_date_text/address_text/victim_*) are
    NULL because the structured source already populates them on the canonical
    rows; this row's purpose is purely to carry weapon + location_type so
    filters and correlation see WY identically to LLM-derived MO.

    Source-span columns are NULL because the values came from structured
    columns, not from narrative offsets.
    """
    session.execute(
        text("""
            INSERT INTO cold_case.case_extractions (
                case_id, extractor_version, prompt_hash, model_id, prompt_tier,
                raw_llm_response, prompt_tokens, completion_tokens,
                cost_usd, notes,
                weapon, weapon_raw_phrase,
                weapon_source_start, weapon_source_end, weapon_low_confidence,
                location_type, location_type_raw_phrase,
                location_type_source_start, location_type_source_end,
                location_type_low_confidence
            )
            VALUES (
                :cid, 'SOURCE', 'source-v1', 'source', 1,
                NULL, NULL, NULL,
                0.0, 'Source-structured MO; no LLM call.',
                :weapon, NULL,
                NULL, NULL, FALSE,
                :loc, NULL,
                NULL, NULL, FALSE
            )
        """),
        {"cid": case_id, "weapon": weapon, "loc": location_type},
    )


def _enqueue_geocoding(
    session: Session,
    *,
    case_id: int,
    address_text: str | None,
    source_county_fips: str | None,
) -> None:
    """Enqueue a geocoding_job directly — no Tier-2 since the address is
    structured in the source. Mirrors OH AG's pattern.

    address_text is NOT NULL on geocoding_job, so we fall back to a bare
    'Wyoming' string when even city is missing — Census + Google can still
    return a state-level centroid which is honest given the inputs.
    """
    addr = address_text or "Wyoming"
    session.execute(
        text("""
            INSERT INTO cold_case.geocoding_job (
                case_id, address_text, state_code, zip_code, county_fips
            )
            VALUES (:cid, :addr, :state, NULL, :fips)
        """),
        {
            "cid": case_id,
            "addr": addr,
            "state": _WY_STATE,
            "fips": source_county_fips,
        },
    )


# --- small utilities -------------------------------------------------------


def _clean(raw: Any) -> str | None:
    """Strip + nullify empties. raw_load already turned empty strings into
    None, but this is defensive against future tweaks."""
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _compose_address(scene_address: str | None, scene_city: str | None) -> str | None:
    """Compose a single address string for the geocoder.

    Returns None when both scene_address and scene_city are absent — at that
    point we have no street- or city-level signal to geocode against.
    """
    parts: list[str] = []
    if scene_address:
        parts.append(scene_address)
    if scene_city:
        parts.append(scene_city)
    if not parts:
        return None
    parts.append(_WY_STATE)
    return ", ".join(parts)

# src/casesignal/etl/adapters/cold_case_ut/transform.py
"""Transform stage for the UT BCI adapter.

Reads raw_cold_case.cold_case_ut_dv<N> and writes canonical model:
  - cold_case.cases (with namus_case_id, ncmec_case_id from CO migration 0004
    and ncic_case_id from UT migration 0005)
  - cold_case.victim — applies ethnicity.classify() to split race/ethnicity
    on the raw 'race' value
  - cold_case.case_photo — one row per photo, first marked is_primary=TRUE
  - cold_case.contact — agency-line shape; UT publishes phone, so populate it
  - Tier-1 extraction job (weapon + location_type from narrative)
  - geocoding_job — directly enqueued (no Tier-2 for UT)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import infer_gender_from_honorific
from casesignal.etl.adapters.cold_case_ut.county_fips import lookup_with_city_fallback
from casesignal.etl.adapters.cold_case_ut.ethnicity import classify as classify_race
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


_UT_STATE = "UT"

# Pin Tier-1 prompt at module load (mirror CO pattern)
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()


def transform_ut(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_ut_dv{context.dataset_version_id}"

    cases_inserted = 0
    photos_inserted = 0
    fips_missing = 0
    extraction_jobs = 0
    geocoding_jobs = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT slug, name, aliases, dob, dod, occupation, age, gender,
                           race, tribal_affiliation, height, weight,
                           eye_color, hair_color, identifying_marks,
                           case_type, case_number,
                           date_of_crime, date_last_seen, date_body_found,
                           city, county, agency_name, agency_phone,
                           ncic_case_id, namus_case_id, narrative,
                           photos_json, source_detail_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY slug
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                # Derive city/county from agency_name when source pages don't
                # publish them in post-meta-keys (BCI typical case).
                effective_city = r.city
                effective_county = r.county
                if not effective_city and not effective_county:
                    dc, dco = _derive_city_county_from_agency(r.agency_name)
                    effective_city = effective_city or dc
                    effective_county = effective_county or dco

                fips = lookup_with_city_fallback(city=effective_city, county=effective_county)
                if fips is None:
                    fips_missing += 1

                # Pick the best available date for incident_date
                incident_date_iso = (
                    _normalize_date(r.date_of_crime)
                    or _normalize_date(r.date_body_found)
                    or _normalize_date(r.date_last_seen)
                )

                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    slug=r.slug,
                    case_number=f"{r.case_number}-{r.slug}" if r.case_number else f"ut-{r.slug}",
                    name=r.name,
                    incident_date_iso=incident_date_iso,
                    city=effective_city,
                    source_county_fips=fips,
                    narrative=r.narrative or "",
                    namus_case_id=r.namus_case_id,
                    ncic_case_id=r.ncic_case_id,
                )
                cases_inserted += 1

                _insert_victim(session, case_id=case_id, r=r)
                _insert_contact(
                    session,
                    case_id=case_id,
                    agency_name=r.agency_name,
                    agency_phone=r.agency_phone,
                    city=effective_city,
                )

                photo_meta = json.loads(r.photos_json) if r.photos_json else []
                for i, p in enumerate(photo_meta):
                    _insert_photo(
                        session,
                        case_id=case_id,
                        photo=p,
                        slug=r.slug,
                        is_primary=(i == 0),
                    )
                    photos_inserted += 1

                # Tier-1 only — same posture as CO/DC (structured demographics
                # cover what Tier-2 would extract).
                enqueue_extraction_job(
                    session,
                    case_id=case_id,
                    prompt_hash=_TIER1_PROMPT_HASH,
                    model_id=_PINNED_MODEL_ID,
                    prompt_tier=1,
                )
                extraction_jobs += 1

                # Geocoding: try to pull a street-level address from the
                # narrative first (BCI doesn't publish per-case `address`
                # but narratives often mention one like "at 3065 S. and
                # 700 E."). Fall back to "{city}, UT" → "Utah" → county-
                # centroid via county_fips.
                extracted = extract_address(r.narrative, city=effective_city, state_code="UT")
                if extracted:
                    address_text = extracted
                elif effective_city:
                    address_text = f"{effective_city}, UT"
                else:
                    address_text = "Utah"
                session.execute(
                    text("""
                        INSERT INTO cold_case.geocoding_job
                            (case_id, address_text, state_code, zip_code, county_fips)
                        VALUES (:cid, :addr, :state, NULL, :fips)
                    """),
                    {
                        "cid": case_id,
                        "addr": address_text,
                        "state": _UT_STATE,
                        "fips": fips,
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
            "UT transform: %d cases (%d w/o county FIPS), %d photos, "
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
    slug: str,
    case_number: str,
    name: str,
    incident_date_iso: str | None,
    city: str | None,
    source_county_fips: str | None,
    narrative: str,
    namus_case_id: str | None,
    ncic_case_id: str | None,
) -> int:
    year = None
    if incident_date_iso and len(incident_date_iso) >= 4:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None

    slug_base = build_case_slug(case_name=name, city=city, state=_UT_STATE, year=year)
    final_slug = resolve_slug_collision(session, slug_base)

    return int(
        session.execute(
            text("""
            INSERT INTO cold_case.cases (
                dataset_version_id, source_case_id, slug,
                case_name, case_type, state, city, source_county_fips,
                incident_date, address,
                about_text, latitude, longitude, geocode_precision,
                namus_case_id, ncmec_case_id, ncic_case_id,
                incident_date_source
            )
            VALUES (
                :dv, :scid, :slug,
                :name, 'homicide', :state, :city, :fips,
                :date, NULL,
                :about, NULL, NULL, NULL,
                :namus, NULL, :ncic,
                CASE WHEN :date IS NULL THEN NULL ELSE 'source' END
            )
            RETURNING case_id
        """),
            {
                "dv": dataset_version_id,
                "scid": case_number,
                "slug": final_slug,
                "name": name,
                "state": _UT_STATE,
                "city": city,
                "fips": source_county_fips,
                "date": incident_date_iso,
                "about": narrative,
                "namus": namus_case_id,
                "ncic": ncic_case_id,
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
    if gender is None and r.narrative:
        gender = infer_gender_from_honorific(r.narrative)
    weight_num = _try_int(_strip_unit(r.weight, "lbs"))

    # Split conflated race/ethnicity per the UT classifier rule
    race, ethnicity = classify_race(r.race)

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
            "age_text": r.age,
            "race": race,
            "height": r.height,
            "weight": weight_num,
            "eye": r.eye_color,
            "hair": r.hair_color,
            "dob": r.dob,
            "dod": r.dod,
            "eth": ethnicity,
            "tribal": r.tribal_affiliation,
            "marks": r.identifying_marks,
            "aliases": r.aliases,
            "occupation": r.occupation,
        },
    )


def _insert_contact(
    session: Session,
    *,
    case_id: int,
    agency_name: str | None,
    agency_phone: str | None,
    city: str | None,
) -> None:
    """UT publishes the agency phone — populate it. Otherwise mirror CO's agency shape."""
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :ln, :phone, :addr, NULL)
        """),
        {"cid": case_id, "ln": agency_name, "phone": agency_phone, "addr": city},
    )


def _insert_photo(
    session: Session,
    *,
    case_id: int,
    photo: dict[str, Any],
    slug: str,
    is_primary: bool,
) -> None:
    filename = photo.get("filename")
    storage_path = f"cold_case_ut/{slug}/{filename}" if filename else None
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


_AGENCY_DETECTIVE_PREFIX_RE = re.compile(
    r"^(?:Detective|Det\.)\s+\S+(?:\s+\S+)?\s+(?:with\s+the\s+)?",
    re.IGNORECASE,
)
_AGENCY_TRAILING_COMMA_RE = re.compile(r",.*$")
_AGENCY_POSSESSIVE_RE = re.compile(r"[‘’’]s\b", re.IGNORECASE)

_AGENCY_COUNTY_RE = re.compile(r"^(.+?)\s+County(?:\s+Sheriff.*)?$", re.IGNORECASE)
_AGENCY_CITY_RE = re.compile(
    r"^(.+?)\s+(?:PD|Police(?:\s+Department)?)$",
    re.IGNORECASE,
)
# Cities published with "City" as canonical part of name (not colloquial)
_PRESERVE_CITY_SUFFIX = frozenset(
    {
        "salt lake city",
        "west valley city",  # canonical — must include "City"
        # "south salt lake city" intentionally absent — canonical is "South Salt Lake"
        "brigham city",
        "cedar city",
    }
)

# Multi-jurisdiction agencies that don’t map to a single city.
# Each entry → (city, county_name) tuple; county_name is looked up in COUNTY_FIPS later.
_KNOWN_MULTI_JURISDICTION_AGENCIES: dict[str, tuple[str | None, str | None]] = {
    "unified police department": (
        None,
        "Salt Lake",
    ),  # UPD covers all of SL County + ~12 contract cities
    "unified pd": (None, "Salt Lake"),
}


def _derive_city_county_from_agency(agency_name: str | None) -> tuple[str | None, str | None]:
    """Heuristically extract (city, county) from a UT BCI agency_name string.

    BCI rarely exposes structured city/county in post-meta-keys but the agency
    name almost always contains one of them. Returns (None, None) when the
    pattern doesn't match (e.g., "SBI", "Unified Police Department").
    """
    if not agency_name:
        return None, None
    s = _AGENCY_DETECTIVE_PREFIX_RE.sub("", agency_name).strip()
    s = _AGENCY_TRAILING_COMMA_RE.sub("", s).strip()
    s = _AGENCY_POSSESSIVE_RE.sub("", s).strip()
    if not s:
        return None, None

    # Check known multi-jurisdiction agencies before regex matching
    known = _KNOWN_MULTI_JURISDICTION_AGENCIES.get(s.lower())
    if known is not None:
        return known

    m = _AGENCY_COUNTY_RE.match(s)
    if m:
        return None, m.group(1).strip()

    m = _AGENCY_CITY_RE.match(s)
    if m:
        candidate = m.group(1).strip()
        # If candidate ends with " City" AND the lowercase form is in the
        # preserve-set, keep "City". Otherwise strip a colloquial " City" suffix.
        if candidate.lower() in _PRESERVE_CITY_SUFFIX:
            return candidate, None
        if candidate.lower().endswith(" city"):
            base = candidate[: -len(" city")].strip()
            # Re-test against preserve-set in case both forms appear
            if (base + " City").lower() in _PRESERVE_CITY_SUFFIX:
                return base + " City", None
            return base, None
        return candidate, None

    return None, None

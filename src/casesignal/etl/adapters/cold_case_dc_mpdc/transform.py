"""Transform stage for the DC MPDC adapter.

Reads raw_cold_case.cold_case_dc_mpdc_dv<N> and writes the canonical
model. DC-specific transformations:
  - state='DC', city='Washington', source_county_fips='11001'
  - Gender extracted from narrative honorific (Mr./Mrs./Ms./Miss) via
    cold_case_dc_mpdc.honorific_regex
  - Lead-detective contact (cold_case.contact is 1:1 with case via a
    UNIQUE constraint; the full multi-detective list stays in the raw
    row's detective_contacts_json for auditability)
  - ONLY Tier-1 extraction job enqueued (NOT Tier-2 — DC narratives
    too sparse to benefit)
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
    infer_gender_from_honorific,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
)
from casesignal.extraction.cold_case.queue_handler import enqueue_extraction_job

logger = logging.getLogger(__name__)


_DC_STATE = "DC"
_DC_CITY = "Washington"
_DC_FIPS = "11001"  # DC's federal-district FIPS code

# Default contact when PDF parsing failed to extract any detectives
_MPDC_DEFAULT_CONTACT_NAME = "MPDC Homicide Branch"
_MPDC_DEFAULT_CONTACT_PHONE = "(202) 645-9600"

# Pin Tier-1 prompt at module load
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()


def transform_dc_mpdc(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_dc_mpdc_dv{context.dataset_version_id}"

    cases_inserted = 0
    victims_inserted = 0
    photos_inserted = 0
    contacts_inserted = 0
    extraction_jobs_enqueued = 0
    gender_extracted = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT source_case_id, ccn, case_name, incident_date_iso,
                           incident_address, narrative, photo_filename,
                           photo_content_type, photo_sha256,
                           detective_contacts_json, source_pdf_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                gender = infer_gender_from_honorific(r.narrative or "")
                if gender:
                    gender_extracted += 1

                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=r.case_name,
                    incident_date_iso=r.incident_date_iso,
                    address=r.incident_address,
                    narrative=r.narrative,
                )
                cases_inserted += 1

                victims_inserted += _insert_victim(
                    session,
                    case_id=case_id,
                    case_name=r.case_name,
                    gender=gender,
                )

                contacts_inserted += _insert_detective_contacts(
                    session,
                    case_id=case_id,
                    contacts_json=r.detective_contacts_json,
                )

                if r.photo_sha256 and r.photo_filename:
                    _insert_photo(
                        session,
                        case_id=case_id,
                        source_case_id=r.source_case_id,
                        filename=r.photo_filename,
                        content_type=r.photo_content_type,
                        sha256=r.photo_sha256,
                        source_url=r.source_pdf_url,
                    )
                    photos_inserted += 1

                # Tier-1 ONLY — no Tier-2 for DC
                enqueue_extraction_job(
                    session,
                    case_id=case_id,
                    prompt_hash=_TIER1_PROMPT_HASH,
                    model_id=_PINNED_MODEL_ID,
                    prompt_tier=1,
                )
                extraction_jobs_enqueued += 1

                # DC skips Tier-2, which is normally what enqueues
                # geocoding jobs. Enqueue directly here using the
                # year-page-scraped address (normalized for Census).
                if r.incident_address:
                    geocode_address = _normalize_for_census(r.incident_address)
                    session.execute(
                        text("""
                            INSERT INTO cold_case.geocoding_job
                                (case_id, address_text, state_code, zip_code, county_fips)
                            VALUES (:cid, :addr, :state, NULL, :fips)
                        """),
                        {
                            "cid": case_id,
                            "addr": geocode_address,
                            "state": _DC_STATE,
                            "fips": _DC_FIPS,
                        },
                    )

            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("transform", cases_inserted)
    if context.logger is not None:
        context.logger.info(
            "DC MPDC transform: %d cases, %d victims (%d with gender from honorific), "
            "%d photos, %d contacts, %d Tier-1 jobs (no Tier-2)",
            cases_inserted,
            victims_inserted,
            gender_extracted,
            photos_inserted,
            contacts_inserted,
            extraction_jobs_enqueued,
        )


def _insert_case(
    session: Session,
    *,
    dataset_version_id: int,
    source_case_id: str,
    case_name: str,
    incident_date_iso: str | None,
    address: str | None,
    narrative: str,
) -> int:
    # Build slug; resolve collisions
    year = None
    if incident_date_iso and len(incident_date_iso) >= 4:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None
    slug_base = build_case_slug(
        case_name=case_name,
        city=_DC_CITY,
        state=_DC_STATE,
        year=year,
    )
    slug = resolve_slug_collision(session, slug_base)

    return int(
        session.execute(
            text("""
            INSERT INTO cold_case.cases (
                dataset_version_id, source_case_id, slug,
                case_name, case_type, state, city, source_county_fips,
                incident_date, incident_date_source, address, address_source,
                about_text, latitude, longitude, geocode_precision
            )
            VALUES (
                :dv, :scid, :slug,
                :name, 'homicide', :state, :city, :fips,
                :date, CASE WHEN :date IS NULL THEN NULL ELSE 'source' END,
                :addr, CASE WHEN :addr IS NULL THEN NULL ELSE 'source' END,
                :about, NULL, NULL, NULL
            )
            RETURNING case_id
        """),
            {
                "dv": dataset_version_id,
                "scid": source_case_id,
                "slug": slug,
                "name": case_name,
                "state": _DC_STATE,
                "city": _DC_CITY,
                "fips": _DC_FIPS,
                "date": incident_date_iso,
                "addr": address,
                "about": narrative,
            },
        ).scalar_one()
    )


def _insert_victim(
    session: Session,
    *,
    case_id: int,
    case_name: str,
    gender: str | None,
) -> int:
    """Parse first/last from case_name; insert one victim row.

    Returns 1 (always — DC is single-victim per case).
    """
    parts = [p.strip() for p in case_name.split() if p.strip()]
    if not parts:
        first, last = "Unknown", ""
    elif len(parts) == 1:
        first, last = parts[0], ""
    else:
        last = parts[-1]
        first = " ".join(parts[:-1])

    session.execute(
        text("""
            INSERT INTO cold_case.victim
                (case_id, first_name, last_name, gender, gender_source)
            VALUES (:cid, :first, :last, :gender, CASE WHEN :gender IS NULL THEN NULL ELSE 'source' END)
        """),
        {"cid": case_id, "first": first, "last": last, "gender": gender},
    )
    return 1


def _insert_detective_contacts(
    session: Session,
    *,
    case_id: int,
    contacts_json: str | None,
) -> int:
    """Insert ONE cold_case.contact row for the lead detective.

    cold_case.contact has UNIQUE(case_id) — the canonical model is 1:1
    case→contact. We pick the first detective from the parsed PDF list
    and store name in first_name/last_name, phone in phone, and any
    role qualifier in address. The full multi-detective list stays in
    raw_cold_case.cold_case_dc_mpdc_dvN.detective_contacts_json for
    auditability and future use.

    Falls back to the MPDC Homicide Branch general line when PDF
    parsing extracted no detectives.
    """
    contacts = []
    if contacts_json:
        try:
            contacts = json.loads(contacts_json)
        except (json.JSONDecodeError, TypeError):
            contacts = []

    if not contacts:
        session.execute(
            text("""
                INSERT INTO cold_case.contact
                    (case_id, first_name, last_name, phone, address, email)
                VALUES (:cid, NULL, :ln, :phone, NULL, NULL)
            """),
            {
                "cid": case_id,
                "ln": _MPDC_DEFAULT_CONTACT_NAME,
                "phone": _MPDC_DEFAULT_CONTACT_PHONE,
            },
        )
        return 1

    lead = contacts[0]
    first_name, last_name = _split_detective_name(lead.get("name"))
    role = lead.get("role")
    address = role if role else None
    session.execute(
        text("""
            INSERT INTO cold_case.contact
                (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, :fn, :ln, :phone, :addr, NULL)
        """),
        {
            "cid": case_id,
            "fn": first_name,
            "ln": last_name,
            "phone": lead.get("phone"),
            "addr": address,
        },
    )
    return 1


_BLOCK_OF_RE = re.compile(r"^(\d+)\s+block\s+of\s+", re.IGNORECASE)
_UNIT_BLOCK_RE = re.compile(r"^Unit\s+block\s+of\s+", re.IGNORECASE)


def _normalize_for_census(address: str) -> str:
    """Convert MPDC's 'NNNN block of Street, QUADRANT' format to a form
    Census's address geocoder can parse.

    Examples:
      "1200 block of U Street, NW"   -> "1200 U Street, NW, Washington, DC"
      "Unit block of K Street, NW"   -> "K Street, NW, Washington, DC"
      "33rd St and Dubois Pl, SE"    -> "33rd St and Dubois Pl, SE, Washington, DC"

    Always appends ", Washington, DC" to disambiguate.
    """
    cleaned = address.strip()
    cleaned = _BLOCK_OF_RE.sub(r"\1 ", cleaned)
    cleaned = _UNIT_BLOCK_RE.sub("", cleaned)
    if "washington" not in cleaned.lower():
        cleaned = f"{cleaned}, Washington, DC"
    return cleaned


def _split_detective_name(name: str | None) -> tuple[str | None, str | None]:
    """Split a detective name into (first_name, last_name).

    Strips the Detective/Det. honorific. Returns (None, None) for empty
    input. Single-token names go to last_name only.
    """
    if not name:
        return None, None
    cleaned = re.sub(r"^(?:Det\.?|Detective)\s+", "", name.strip(), flags=re.IGNORECASE)
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return None, parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _insert_photo(
    session: Session,
    *,
    case_id: int,
    source_case_id: str,
    filename: str,
    content_type: str | None,
    sha256: str,
    source_url: str | None,
) -> None:
    storage_path = f"cold_case_dc_mpdc/{source_case_id}/{filename}"
    session.execute(
        text("""
            INSERT INTO cold_case.case_photo
                (case_id, filename, content_type, alt_text,
                 sha256, is_primary, source_url, storage_path)
            VALUES
                (:cid, :filename, :ctype, NULL,
                 :sha, TRUE, :src, :storage_path)
        """),
        {
            "cid": case_id,
            "filename": filename,
            "ctype": content_type or "application/octet-stream",
            "sha": sha256,
            "src": source_url,
            "storage_path": storage_path,
        },
    )

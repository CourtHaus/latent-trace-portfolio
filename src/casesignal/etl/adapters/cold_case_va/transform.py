"""Transform raw_cold_case.cases_dv<N> rows into cold_case.cases / victim / contact."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash as _compute_extraction_prompt_hash,
)
from casesignal.extraction.cold_case.prompt_loader import (
    get_pinned_model_id as _get_pinned_model_id,
)
from casesignal.extraction.cold_case.prompt_loader import (
    load_tier1_prompt_template as _load_extraction_prompt_template,
)

# Pinned at module load so every transform run in this process uses a consistent
# (prompt_hash, model_id) pair. The queue worker picks the same pair on its side.
_CURRENT_EXTRACTION_PROMPT_HASH = _compute_extraction_prompt_hash(
    _load_extraction_prompt_template()
)
_CURRENT_EXTRACTION_MODEL_ID = _get_pinned_model_id()


_WKT_POINT_RE = re.compile(
    r"^\s*POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*\)\s*$"
)

# source_case_id arrives as scientific notation (e.g., "2.0041E+11") when the
# source CSV is opened in Excel before export — Excel auto-converts long
# numeric case IDs to exponent form. The true ID is preserved in case_name
# ("Jurisdiction - <digits> - Victim"), so we extract it there.
# Covers "2.0041E+11", "2.0041e+11", "8.10324E+12" etc.
_SCIENTIFIC_ID_RE = re.compile(r"^[0-9.]+[Ee]\+?[0-9]+$")
# Matches a run of 10+ consecutive digits inside case_name. Real VSPCCD IDs are
# 10–13 digits; victim names and dates contain no digit runs that long.
_EMBEDDED_DIGITS_RE = re.compile(r"([0-9]{10,})")

# Map full US state names to their two-letter postal abbreviation.
# Only states observed in the VSPCCD extract are listed; extend as needed.
_STATE_NAME_TO_ABBR: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}


def _normalize_state(value: str | None) -> str:
    """Normalize a state field to a two-letter postal abbreviation.

    Accepts full names (e.g. 'Virginia') or existing abbreviations (e.g. 'VA').
    Returns 'VA' as the default for this source if the value is absent/unknown.
    """
    if not value:
        return "VA"
    stripped = value.strip()
    # Already an abbreviation (2 chars, all alpha)
    if len(stripped) == 2 and stripped.isalpha():
        return stripped.upper()
    # Full name lookup
    abbr = _STATE_NAME_TO_ABBR.get(stripped.lower())
    if abbr:
        return abbr
    # Fallback: truncate to 2 chars (preserves prior behaviour for unexpected values)
    return stripped[:2].upper()


def _normalize_source_case_id(raw_id: str | None, case_name: str | None) -> str | None:
    """Repair scientific-notation source_case_id values at ingestion time.

    If raw_id matches the scientific pattern (e.g., "2.0041E+11") and case_name
    contains a 10+ digit run, return the extracted digits. Otherwise return
    raw_id unchanged. None/empty input passes through.

    Complements migrations 0014 + 0015, which cleaned historical data. This
    stops the issue from recurring on future re-ingestions of the same source.
    """
    if raw_id is None or raw_id == "":
        return raw_id
    if not _SCIENTIFIC_ID_RE.match(raw_id):
        return raw_id
    if case_name is None:
        return raw_id
    match = _EMBEDDED_DIGITS_RE.search(case_name)
    if match is None:
        return raw_id
    return match.group(1)


def _nullify(value: str | None) -> str | None:
    """Collapse empty / whitespace-only strings to None."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_wkt_point(value: str | None) -> tuple[Decimal | None, Decimal | None]:
    """Parse 'POINT (lon lat)' -> (latitude, longitude). Returns (None, None) if unparseable."""
    if value is None or not value.strip():
        return (None, None)
    match = _WKT_POINT_RE.match(value)
    if not match:
        return (None, None)
    try:
        lon = Decimal(match.group(1))
        lat = Decimal(match.group(2))
    except InvalidOperation:
        return (None, None)
    return (lat, lon)


def _parse_date(value: str | None) -> date | None:
    """Parse US-format MM/DD/YYYY; return None for empty / malformed."""
    if value is None or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _parse_weight(value: str | None) -> int | None:
    """Parse integer weight; None for empty or non-numeric."""
    if value is None or not value.strip():
        return None
    stripped = value.strip()
    try:
        return int(stripped)
    except ValueError:
        return None


def transform_cold_case(context: PipelineContext) -> None:
    logger = context.logger
    if logger is None:
        raise RuntimeError("PipelineContext.logger must be set before running stages.")

    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set (run register_source first).")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError(
            "session_factory in pipeline context metadata is not a SQLAlchemy sessionmaker."
        )

    raw_table = f"raw_cold_case.cases_dv{context.dataset_version_id}"

    with session_factory() as session:
        try:
            # Clear prior transform output for this dataset_version_id (re-run safe)
            session.execute(
                text("DELETE FROM cold_case.cases WHERE dataset_version_id = :dv"),
                {"dv": context.dataset_version_id},
            )
            # CASCADE ON DELETE cleans victim/contact children automatically.

            rows = (
                session.execute(
                    text(f"SELECT * FROM {raw_table} WHERE dataset_version_id = :dv"),
                    {"dv": context.dataset_version_id},
                )
                .mappings()
                .all()
            )

            cases_inserted = 0
            victims_inserted = 0
            contacts_inserted = 0

            for r in rows:
                lat, lon = _parse_wkt_point(r.get("geographic-location"))
                case_name = _nullify(r.get("case_name")) or "(unnamed case)"
                city = _nullify(r.get("city"))
                state = _normalize_state(r.get("state"))
                incident_date = _parse_date(r.get("incident-date"))
                year = incident_date.year if incident_date else None
                base = build_case_slug(case_name, city, state, year)
                # Note: slug is reserved here via DB query. If the INSERT below hits
                # ON CONFLICT DO NOTHING (duplicate (dataset_version_id, source_case_id)),
                # this slug is not written. A future row with the same base can still
                # claim 'base' cleanly, but the `-N` sequence may have gaps in it.
                # Cosmetic, not correctness — URLs still resolve uniquely.
                slug = resolve_slug_collision(session, base)
                raw_src_id = _nullify(r.get("vspccd-number")) or _nullify(r.get("_id")) or ""
                src_id = _normalize_source_case_id(raw_src_id, case_name) or raw_src_id
                if src_id != raw_src_id:
                    logger.warning(
                        "repaired scientific-notation source_case_id: %r -> %r (case: %r)",
                        raw_src_id,
                        src_id,
                        case_name,
                    )
                case_id = session.execute(
                    text("""
                        INSERT INTO cold_case.cases (
                            dataset_version_id, source_case_id, case_name, case_type,
                            incident_date, incident_date_source,
                            address, address_source,
                            city, state, about_text,
                            latitude, longitude, slug
                        )
                        VALUES (
                            :dv, :src_id, :name, :type,
                            :incident_date, CASE WHEN :incident_date IS NULL THEN NULL ELSE 'source' END,
                            :address, CASE WHEN :address IS NULL THEN NULL ELSE 'source' END,
                            :city, :state, :about, :lat, :lon, :slug
                        )
                        ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
                        RETURNING case_id
                        """),
                    {
                        "dv": context.dataset_version_id,
                        "src_id": src_id,
                        "name": case_name,
                        "type": _nullify(r.get("type")) or "unknown",
                        "incident_date": incident_date,
                        "address": _nullify(r.get("address")),
                        "city": city,
                        "state": state,
                        "about": _nullify(r.get("about")),
                        "lat": lat,
                        "lon": lon,
                        "slug": slug,
                    },
                ).scalar_one_or_none()
                if case_id is None:
                    # Duplicate source_case_id for this dataset_version; skip
                    # victim/contact insertion for this row.
                    continue
                cases_inserted += 1

                # C1 hook: enqueue extraction job in the same transaction as the case
                # INSERT. Same session = same txn = rollback-safe (no orphan jobs on
                # rolled-back cases).
                session.execute(
                    text("""
                        INSERT INTO cold_case.extraction_job (case_id, prompt_hash, model_id)
                        VALUES (:case_id, :prompt_hash, :model_id)
                        """),
                    {
                        "case_id": case_id,
                        "prompt_hash": _CURRENT_EXTRACTION_PROMPT_HASH,
                        "model_id": _CURRENT_EXTRACTION_MODEL_ID,
                    },
                )

                # One victim per row (CSV is row-per-case with at most one victim set)
                victim_first = _nullify(r.get("victim-fields_first-name"))
                victim_last = _nullify(r.get("victim-fields_last-name"))
                if victim_first or victim_last:
                    session.execute(
                        text("""
                            INSERT INTO cold_case.victim (
                                case_id, first_name, last_name,
                                gender, gender_source,
                                height_text, weight_num,
                                age_text, age_source,
                                race, race_source,
                                eye_color, hair_color
                            )
                            VALUES (
                                :case_id, :fn, :ln,
                                :gender, CASE WHEN :gender IS NULL THEN NULL ELSE 'source' END,
                                :height, :weight,
                                :age, CASE WHEN :age IS NULL THEN NULL ELSE 'source' END,
                                :race, CASE WHEN :race IS NULL THEN NULL ELSE 'source' END,
                                :eye, :hair
                            )
                            """),
                        {
                            "case_id": case_id,
                            "fn": victim_first,
                            "ln": victim_last,
                            "gender": _nullify(r.get("victim-fields_gender")),
                            "height": _nullify(r.get("victim-fields_height")),
                            "weight": _parse_weight(r.get("victim-fields_weight")),
                            "age": _nullify(r.get("victim-fields_age")),
                            "race": _nullify(r.get("victim-fields_race")),
                            "eye": _nullify(r.get("victim-fields_eye-color")),
                            "hair": _nullify(r.get("victim-fields_hair-color")),
                        },
                    )
                    victims_inserted += 1

                # Contact is 1:1 with case; insert if any contact field present
                c_first = _nullify(r.get("contact-first-name"))
                c_last = _nullify(r.get("contact-last-name"))
                c_phone = _nullify(r.get("contact-phone-number"))
                c_email = _nullify(r.get("contact-email"))
                if any((c_first, c_last, c_phone, c_email)):
                    session.execute(
                        text("""
                            INSERT INTO cold_case.contact (
                                case_id, first_name, last_name, phone, address, email
                            )
                            VALUES (:case_id, :fn, :ln, :phone, :address, :email)
                            """),
                        {
                            "case_id": case_id,
                            "fn": c_first,
                            "ln": c_last,
                            "phone": c_phone,
                            "address": _nullify(r.get("contact-address")),
                            "email": c_email,
                        },
                    )
                    contacts_inserted += 1

            session.commit()
            session.execute(text("ANALYZE cold_case.cases"))
            session.execute(text("ANALYZE cold_case.victim"))
            session.execute(text("ANALYZE cold_case.contact"))
            session.commit()

        except Exception:
            session.rollback()
            raise

    logger.info(
        "Cold case VA transform: %d cases / %d victims / %d contacts inserted.",
        cases_inserted,
        victims_inserted,
        contacts_inserted,
    )
    context.set_metadata("transform_cases_inserted", cases_inserted)
    context.set_metadata("transform_victims_inserted", victims_inserted)
    context.set_metadata("transform_contacts_inserted", contacts_inserted)

    # Absorbed from former validate_core stage — assertions on canonical rows.
    from casesignal.etl.adapters.cold_case_va.validation import validate_cold_case_core

    validate_cold_case_core(context)

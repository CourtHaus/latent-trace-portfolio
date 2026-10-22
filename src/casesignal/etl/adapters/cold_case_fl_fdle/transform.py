"""Transform stage for the FL FDLE adapter."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, sessionmaker

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.etl.services.normalizers import (
    clean_sentinel,
    normalize_gender,
    try_int,
)
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

_FL_STATE = "FL"
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_TIER2_PROMPT_HASH = compute_prompt_hash(load_tier2_v4_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()


def _is_sentence_shaped(text: str | None) -> bool:
    """True when a title reads like prose — a leaked case summary, not a title.

    FDLE titles are short proper-noun phrases ("Avery Exampleton Homicide (Alachua
    CSO)"); a few records (confirmed in the live source) have the summary typed
    into the title field instead, e.g. "victim's nude body was discovered ...".
    """
    value = (text or "").strip()
    if not value:
        return False
    if value.endswith(")"):
        # Real FDLE titles end with the agency tag, e.g. "... (Alachua CSO)";
        # leaked summaries end with prose punctuation. This separates a long
        # multi-victim title from a narrative that was typed into the title slot.
        return False
    if value[:1].islower() or value.endswith("."):
        return True
    return len(value.split()) >= 8


def _synthesize_case_name(
    case_title: str | None,
    victim_name: str | None,
    case_type: str,
    source_case_id: str,
    title_is_leaked: bool = False,
) -> str:
    title = clean_sentinel(case_title)
    if title and not title_is_leaked:
        return title
    name = clean_sentinel(victim_name)
    if name and name.strip(", "):  # real content, not just commas/spaces
        # FDLE victim_name is "Last, First" — reuse the shared splitter, which
        # handles multi-comma ("Last, First, Jr"), trailing-comma, and no-comma.
        first, last = _split_fdle_name(name)
        display = f"{first} {last}".strip()
        return f"{display} — {(case_type or 'Cold Case').title()}"
    return f"Unidentified — {(case_type or 'Cold Case').title()} ({source_case_id})"


def _derive_narrative(narrative: str | None, case_title: str | None,
                      title_is_leaked: bool) -> str:
    """Use the real narrative; when it's empty and the summary leaked into the
    title (source quirk), fall back to the title so Tier-2 has text to extract."""
    n = clean_sentinel(narrative)
    if n:
        return n
    if title_is_leaked:
        return clean_sentinel(case_title) or ""
    return ""


def transform_fl(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_fl_fdle_dv{context.dataset_version_id}"
    cases_inserted = 0
    photos_inserted = 0
    extraction_jobs = 0
    geocoding_jobs = 0

    with session_factory() as session:
        try:
            _delete_existing_canonical_rows(session, dataset_version_id=context.dataset_version_id)
            raw_rows = session.execute(
                text(f"""
                    SELECT dataset_version_id, source_case_id, case_title, victim_name,
                           case_type, incident_date, incident_address, incident_city,
                           agency_address, reporting_agency, agency_phone, gender, race, height,
                           weight_lbs, dob, narrative, photos_json, source_detail_url
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                # A few FDLE records have the case summary typed into the title
                # field with an empty narrative (confirmed source quirk). Detect
                # that and route the text to the narrative, not the case_name.
                title_is_leaked = (
                    bool(clean_sentinel(r.case_title))
                    and not clean_sentinel(r.narrative)
                    and _is_sentence_shaped(r.case_title)
                )
                case_name = _synthesize_case_name(
                    r.case_title,
                    r.victim_name,
                    _normalize_case_type(r.case_type),
                    r.source_case_id,
                    title_is_leaked=title_is_leaked,
                )
                incident_date_iso = _normalize_fl_date(r.incident_date)
                city = clean_sentinel(r.incident_city)
                address = clean_sentinel(r.incident_address)
                case_id = _insert_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=case_name,
                    case_type=_normalize_case_type(r.case_type),
                    incident_date_iso=incident_date_iso,
                    address=address,
                    city=city,
                    narrative=_derive_narrative(r.narrative, r.case_title, title_is_leaked),
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

                for tier, prompt_hash in (
                    (1, _TIER1_PROMPT_HASH),
                    (2, _TIER2_PROMPT_HASH),
                ):
                    enqueue_extraction_job(
                        session,
                        case_id=case_id,
                        prompt_hash=prompt_hash,
                        model_id=_PINNED_MODEL_ID,
                        prompt_tier=tier,
                    )
                    extraction_jobs += 1

                if address:
                    session.execute(
                        text("""
                            INSERT INTO cold_case.geocoding_job
                                (case_id, address_text, state_code, zip_code, county_fips)
                            VALUES (:cid, :addr, :state, NULL, NULL)
                        """),
                        {
                            "cid": case_id,
                            "addr": address,
                            "state": _FL_STATE,
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
            "FL FDLE transform: %d cases, %d photos, %d extraction jobs, %d geocoding jobs",
            cases_inserted,
            photos_inserted,
            extraction_jobs,
            geocoding_jobs,
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
    address: str | None,
    city: str | None,
    narrative: str,
) -> int:
    year = None
    if incident_date_iso:
        try:
            year = int(incident_date_iso[:4])
        except ValueError:
            year = None
    slug_base = build_case_slug(case_name=case_name, city=city, state=_FL_STATE, year=year)
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
                    :name, :case_type, :state, :city, NULL,
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
                "case_type": case_type,
                "state": _FL_STATE,
                "city": city,
                "date": incident_date_iso,
                "addr": address,
                "about": narrative,
            },
        ).scalar_one()
    )


def _insert_victim(session: Session, *, case_id: int, r: Row[Any]) -> None:
    first_name, last_name = _split_fdle_name(clean_sentinel(r.victim_name))
    gender = normalize_gender(r.gender)
    race = clean_sentinel(r.race)
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
                NULL, NULL,
                :dob, NULL, NULL, NULL,
                NULL, NULL, NULL,
                CASE WHEN :gender IS NULL THEN NULL ELSE 'source' END,
                NULL,
                CASE WHEN :race IS NULL THEN NULL ELSE 'source' END
            )
        """),
        {
            "cid": case_id,
            "fn": first_name,
            "ln": last_name,
            "gender": gender,
            "race": race,
            "height": clean_sentinel(r.height),
            "weight": try_int(r.weight_lbs),
            "dob": clean_sentinel(r.dob),
        },
    )


def _insert_contact(session: Session, *, case_id: int, r: Row[Any]) -> None:
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, first_name, last_name, phone, address, email)
            VALUES (:cid, NULL, :agency, :phone, :addr, NULL)
        """),
        {
            "cid": case_id,
            "agency": clean_sentinel(r.reporting_agency),
            "phone": clean_sentinel(r.agency_phone),
            "addr": clean_sentinel(r.agency_address),
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
        f"cold_case_fl_fdle/{safe_filename(source_case_id)}/{filename}" if filename else None
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


def _normalize_case_type(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if "missing" in value:
        return "missing_person"
    if "homicide" in value or "death" in value:
        return "homicide"
    return "cold_case"


def _normalize_fl_date(raw: str | None) -> str | None:
    value = clean_sentinel(raw)
    if not value:
        return None
    for fmt in ("%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _split_fdle_name(name: str | None) -> tuple[str, str]:
    if not name:
        return "Unknown", ""
    if "," in name:
        last, first = [part.strip() for part in name.split(",", 1)]
        return first or "Unknown", last
    parts = [part.strip() for part in name.split() if part.strip()]
    if not parts:
        return "Unknown", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]

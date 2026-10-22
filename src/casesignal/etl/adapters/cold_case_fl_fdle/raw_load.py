"""Raw-load stage for the FL FDLE adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.services.photo_helpers import (
    PHOTO_EXT_BY_CONTENT_TYPE,
    safe_filename,
    sha256_of_file,
)
from casesignal.etl.services.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

_PHOTO_DIR_ROOT = Path("data/photos/cold_case_fl_fdle")


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_fl_fdle_dv{dataset_version_id}"


def _ensure_table(session: Session, dataset_version_id: int) -> str:
    table = _raw_table_name(dataset_version_id)
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            dataset_version_id INTEGER NOT NULL,
            source_case_id     TEXT NOT NULL,
            case_title         TEXT,
            victim_name        TEXT,
            case_type          TEXT,
            incident_date      TEXT,
            incident_address   TEXT,
            incident_city      TEXT,
            reporting_agency   TEXT,
            agency_phone       TEXT,
            agency_address     TEXT,
            gender             TEXT,
            race               TEXT,
            height             TEXT,
            weight_lbs         INTEGER,
            dob                TEXT,
            narrative          TEXT,
            photos_json        TEXT,
            source_detail_url  TEXT NOT NULL,
            PRIMARY KEY (dataset_version_id, source_case_id)
        )
    """))
    session.commit()
    return table


def load_fl_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    entries: list[dict[str, Any]] = context.get_metadata("fl_entries") or []
    if not entries:
        raise RuntimeError("fl_entries missing; prepare_input must run first.")

    polite = context.get_metadata("polite_http")
    if polite is None:
        raise RuntimeError("polite_http metadata missing; prepare_input must run first.")

    session_factory = context.get_metadata("session_factory")
    if session_factory is not None:
        session = session_factory()
        owns_session = True
    elif context.session is not None:
        session = context.session
        owns_session = False
    else:
        raise RuntimeError(
            "FL FDLE raw_load requires either context.session or "
            "context.metadata['session_factory']."
        )

    dvid = context.dataset_version_id
    table = _ensure_table(session, dvid)
    max_photo_failure_ratio = float(context.get_metadata("max_photo_failure_ratio") or 0.5)

    inserted = 0
    failed = 0
    photos_attempted = 0
    photos_fetched = 0
    photos_failed = 0

    try:
        session.execute(text(f"DELETE FROM {table} WHERE dataset_version_id = :dv"), {"dv": dvid})
        session.commit()
        for entry in entries:
            try:
                source_case_id = str(entry["source_case_id"])
                photo_records: list[dict[str, Any]] = []
                for idx, photo in enumerate(entry.get("photos") or []):
                    if not photo.get("source_url"):
                        continue
                    photos_attempted += 1
                    try:
                        record = _download_photo(
                            polite=polite,
                            source_case_id=source_case_id,
                            idx=idx,
                            photo=photo,
                        )
                    except Exception as exc:
                        photos_failed += 1
                        logger.warning(
                            "FL FDLE photo fetch failed for case %s: %r",
                            source_case_id,
                            exc,
                        )
                        continue
                    if record is not None:
                        photo_records.append(record)
                        photos_fetched += 1
                    else:
                        photos_failed += 1

                session.execute(
                    text(f"""
                        INSERT INTO {table} (
                            dataset_version_id, source_case_id, case_title, victim_name,
                            case_type, incident_date, incident_address, incident_city,
                            reporting_agency, agency_phone, agency_address, gender, race, height,
                            weight_lbs, dob, narrative, photos_json, source_detail_url
                        )
                        VALUES (
                            :dv, :source_case_id, :case_title, :victim_name,
                            :case_type, :incident_date, :incident_address, :incident_city,
                            :reporting_agency, :agency_phone, :agency_address, :gender, :race, :height,
                            :weight_lbs, :dob, :narrative, :photos_json, :source_detail_url
                        )
                        ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
                    """),
                    {
                        "dv": dvid,
                        "source_case_id": source_case_id,
                        "case_title": entry.get("case_title"),
                        "victim_name": entry.get("victim_name"),
                        "case_type": entry.get("case_type"),
                        "incident_date": entry.get("incident_date"),
                        "incident_address": entry.get("incident_address"),
                        "incident_city": entry.get("incident_city"),
                        "reporting_agency": entry.get("reporting_agency"),
                        "agency_phone": entry.get("agency_phone"),
                        "agency_address": entry.get("agency_address"),
                        "gender": entry.get("gender"),
                        "race": entry.get("race"),
                        "height": entry.get("height"),
                        "weight_lbs": entry.get("weight_lbs"),
                        "dob": entry.get("dob"),
                        "narrative": entry.get("narrative"),
                        "photos_json": json.dumps(photo_records),
                        "source_detail_url": entry.get("source_detail_url"),
                    },
                )
                inserted += 1
            except Exception as exc:
                failed += 1
                logger.warning("FL FDLE raw row failed: %r", exc)

        session.commit()
    finally:
        if owns_session:
            session.close()

    logger_fn = context.logger.info if context.logger is not None else logger.info
    logger_fn(
        "FL FDLE raw_load: inserted=%d failed=%d photos_attempted=%d "
        "photos_fetched=%d photos_failed=%d "
        "(of %d entries)",
        inserted,
        failed,
        photos_attempted,
        photos_fetched,
        photos_failed,
        len(entries),
    )
    context.increment_row_count("load_raw", inserted)

    if inserted < 50 and len(entries) >= 50:
        raise RuntimeError(
            f"FL FDLE raw_load inserted only {inserted} rows out of {len(entries)}; "
            "refusing to proceed."
        )
    if failed:
        raise RuntimeError(f"FL FDLE raw_load had {failed} raw row failure(s); refusing to proceed.")
    if photos_attempted:
        photo_failure_ratio = photos_failed / photos_attempted
        if photo_failure_ratio > max_photo_failure_ratio:
            raise RuntimeError(
                "FL FDLE photo failure ratio exceeded threshold: "
                f"{photos_failed}/{photos_attempted} ({photo_failure_ratio:.1%}) "
                f"> {max_photo_failure_ratio:.1%}."
            )


def _download_photo(
    *,
    polite: Any,
    source_case_id: str,
    idx: int,
    photo: dict[str, Any],
) -> dict[str, Any] | None:
    source_url = photo.get("source_url")
    if not source_url:
        return None

    head_response = polite.head(source_url)
    content_type = head_response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    ext = PHOTO_EXT_BY_CONTENT_TYPE.get(content_type)
    if ext is None:
        logger.warning(
            "FL FDLE photo unrecognized Content-Type %r for %s; skipping",
            content_type,
            source_url,
        )
        return None

    case_dir = _PHOTO_DIR_ROOT / safe_filename(source_case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    hint = safe_filename(str(photo.get("filename_hint") or f"{idx:02d}_photo"))
    if not hint.lower().endswith(f".{ext}"):
        hint = f"{hint}.{ext}"
    filename = safe_filename(f"{idx:02d}_{hint}")
    dest = case_dir / filename
    polite.fetch_to_file(source_url, dest)

    return {
        "filename": filename,
        "alt": photo.get("alt"),
        "is_primary": idx == 0,
        "sha256": sha256_of_file(dest),
        "source_url": source_url,
        "content_type": content_type,
    }

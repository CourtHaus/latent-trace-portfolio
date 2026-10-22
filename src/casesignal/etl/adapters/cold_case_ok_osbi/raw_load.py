"""Raw-load stage for the OK OSBI adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.adapters.cold_case_ok_osbi.adapter import _MIN_EXPECTED_CASES
from casesignal.etl.services.photo_helpers import (
    PHOTO_EXT_BY_CONTENT_TYPE,
    safe_filename,
    sha256_of_file,
)
from casesignal.etl.services.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

_PHOTO_DIR_ROOT = Path("data/photos/cold_case_ok_osbi")


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_ok_osbi_dv{dataset_version_id}"


def _ensure_table(session: Session, dataset_version_id: int) -> str:
    table = _raw_table_name(dataset_version_id)
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            dataset_version_id INTEGER NOT NULL,
            source_case_id     TEXT NOT NULL,
            name               TEXT NOT NULL,
            case_name          TEXT NOT NULL,
            case_type          TEXT,
            date_text          TEXT,
            incident_date_iso  TEXT,
            narrative          TEXT,
            contact_text       TEXT,
            source_range_url   TEXT,
            photos_json        TEXT,
            PRIMARY KEY (dataset_version_id, source_case_id)
        )
    """))
    session.commit()
    return table


def load_ok_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    entries: list[dict[str, Any]] = context.get_metadata("ok_entries") or []
    if not entries:
        raise RuntimeError("ok_entries missing; prepare_input must run first.")

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
            "OK OSBI raw_load requires either context.session or "
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
                photos = [entry["photo"]] if entry.get("photo") else []
                for idx, photo in enumerate(photos):
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
                            "OK OSBI photo fetch failed for case %s: %r",
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
                            dataset_version_id, source_case_id, name, case_name,
                            case_type, date_text, incident_date_iso, narrative,
                            contact_text, source_range_url, photos_json
                        )
                        VALUES (
                            :dv, :source_case_id, :name, :case_name,
                            :case_type, :date_text, :incident_date_iso, :narrative,
                            :contact_text, :source_range_url, :photos_json
                        )
                        ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
                    """),
                    {
                        "dv": dvid,
                        "source_case_id": source_case_id,
                        "name": entry.get("name"),
                        "case_name": entry.get("case_name"),
                        "case_type": entry.get("case_type"),
                        "date_text": entry.get("date_text"),
                        "incident_date_iso": entry.get("incident_date_iso"),
                        "narrative": entry.get("narrative"),
                        "contact_text": entry.get("contact_text"),
                        "source_range_url": entry.get("source_range_url"),
                        "photos_json": json.dumps(photo_records),
                    },
                )
                inserted += 1
            except Exception as exc:
                failed += 1
                logger.warning("OK OSBI raw row failed: %r", exc)

        session.commit()
    finally:
        if owns_session:
            session.close()

    logger_fn = context.logger.info if context.logger is not None else logger.info
    logger_fn(
        "OK OSBI raw_load: inserted=%d failed=%d photos_attempted=%d "
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

    if inserted < _MIN_EXPECTED_CASES and len(entries) >= _MIN_EXPECTED_CASES:
        raise RuntimeError(
            f"OK OSBI raw_load inserted only {inserted} rows out of {len(entries)}; "
            "refusing to proceed."
        )
    if failed:
        raise RuntimeError(f"OK OSBI raw_load had {failed} raw row failure(s); refusing to proceed.")
    if photos_attempted:
        photo_failure_ratio = photos_failed / photos_attempted
        if photo_failure_ratio > max_photo_failure_ratio:
            raise RuntimeError(
                "OK OSBI photo failure ratio exceeded threshold: "
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
            "OK OSBI photo unrecognized Content-Type %r for %s; skipping",
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

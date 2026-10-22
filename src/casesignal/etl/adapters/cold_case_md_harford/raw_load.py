"""Raw-load stage for the Harford County adapter.

Page was already parsed in prepare_input; load_raw downloads photos
and writes one row per CaseSection into raw_cold_case.cold_case_md_harford_dv<N>.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.adapters.cold_case_md_harford.scrape import CaseSection
from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
    download_case_photo,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import (
    FetchTooLarge,
    PoliteHTTPClient,
)

logger = logging.getLogger(__name__)


_SOURCE_KEY = "cold_case_md_harford"


def load_harford_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set (run register_source first).")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    polite = context.get_metadata("polite_http")
    if not isinstance(polite, PoliteHTTPClient):
        raise TypeError("polite_http metadata is not a PoliteHTTPClient.")

    sections: list[CaseSection] = context.get_metadata("harford_sections") or []
    if not sections:
        raise RuntimeError("harford_sections missing from context metadata.")

    table_ident = _raw_table_name(context.dataset_version_id)
    rows_inserted = 0
    photos_downloaded = 0
    photos_failed = 0
    placeholders_skipped = 0

    with session_factory() as session:
        try:
            session.execute(text(_create_raw_table_sql(table_ident)))
            session.execute(
                text(f"DELETE FROM {table_ident} WHERE dataset_version_id = :dv"),
                {"dv": context.dataset_version_id},
            )
            session.commit()

            for s in sections:
                photo_local_path: Path | None = None
                photo_sha256: str | None = None
                if s.photo_url and s.photo_filename:
                    try:
                        result = download_case_photo(
                            polite,
                            s.photo_url,
                            source_key=_SOURCE_KEY,
                            source_case_id=s.source_case_id,
                            sanitized_filename=s.photo_filename,
                        )
                        if result is None:
                            placeholders_skipped += 1
                        else:
                            photo_local_path, photo_sha256 = result
                            photos_downloaded += 1
                    except (FetchTooLarge, Exception) as exc:
                        logger.info(
                            "Harford photo fetch failed for %s: %r",
                            s.source_case_id,
                            exc,
                        )
                        photos_failed += 1

                _insert_raw_row(
                    session,
                    table_ident=table_ident,
                    dataset_version_id=context.dataset_version_id,
                    section=s,
                    photo_sha256=photo_sha256,
                    photo_local_path=str(photo_local_path) if photo_local_path else None,
                )
                rows_inserted += 1
                if rows_inserted % 10 == 0:
                    session.commit()

            session.commit()
            session.execute(text(f"ANALYZE {table_ident}"))
            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("load_raw", rows_inserted)
    if context.logger is not None:
        context.logger.info(
            "Harford raw load: %d rows -> %s; photos %d downloaded, %d placeholders, %d failed",
            rows_inserted,
            table_ident,
            photos_downloaded,
            placeholders_skipped,
            photos_failed,
        )

    if rows_inserted < 15:
        raise RuntimeError(f"Harford raw load produced only {rows_inserted} rows; expected >= 15.")


def _content_type_from_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_md_harford_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id    INT NOT NULL,
        source_case_id        TEXT NOT NULL,
        case_name             TEXT NOT NULL,
        narrative_text        TEXT NOT NULL,
        photo_filename        TEXT,
        photo_content_type    TEXT,
        photo_alt_text        TEXT,
        photo_source_url      TEXT,
        photo_sha256          TEXT,
        photo_local_path      TEXT,
        PRIMARY KEY (dataset_version_id, source_case_id)
    )
    """


def _insert_raw_row(
    session: Session,
    *,
    table_ident: str,
    dataset_version_id: int,
    section: CaseSection,
    photo_sha256: str | None,
    photo_local_path: str | None,
) -> None:
    photo_content_type = (
        _content_type_from_filename(section.photo_filename) if section.photo_filename else None
    )
    session.execute(
        text(f"""
            INSERT INTO {table_ident} (
                dataset_version_id, source_case_id, case_name, narrative_text,
                photo_filename, photo_content_type, photo_alt_text,
                photo_source_url, photo_sha256, photo_local_path
            )
            VALUES (
                :dv, :scid, :name, :narr,
                :pf, :pct, :pat, :psu, :psha, :plp
            )
            ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
        """),
        {
            "dv": dataset_version_id,
            "scid": section.source_case_id,
            "name": section.case_name,
            "narr": section.narrative_text,
            "pf": section.photo_filename,
            "pct": photo_content_type,
            "pat": section.photo_alt_text,
            "psu": section.photo_url,
            "psha": photo_sha256,
            "plp": photo_local_path,
        },
    )

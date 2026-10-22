"""Raw-load stage for the Charles County adapter.

Fetches each detail page (narrative + photo URL discovery), downloads
photos via shared helper, writes one row per case to
raw_cold_case.cold_case_md_charles_dv<N>.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.adapters.cold_case_md_charles.scrape import (
    CaseRef,
    parse_detail,
)
from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
    download_case_photo,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import (
    FetchTooLarge,
    PoliteHTTPClient,
)

logger = logging.getLogger(__name__)
_SOURCE_KEY = "cold_case_md_charles"


def load_charles_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set (run register_source first).")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    polite = context.get_metadata("polite_http")
    if not isinstance(polite, PoliteHTTPClient):
        raise TypeError("polite_http metadata is not a PoliteHTTPClient.")

    refs: list[CaseRef] = context.get_metadata("charles_refs") or []
    if not refs:
        raise RuntimeError("charles_refs missing from context metadata.")

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

            for ref in refs:
                response = polite.get(ref.detail_url)
                detail = parse_detail(response.text, case_ref_url=ref.detail_url)
                if len(detail.narrative_text) < 50:
                    logger.info(
                        "Charles detail too short for %s; skipping",
                        ref.source_case_id,
                    )
                    continue

                photo_local_path: Path | None = None
                photo_sha256: str | None = None
                if detail.photo_url and detail.photo_filename:
                    try:
                        result = download_case_photo(
                            polite,
                            detail.photo_url,
                            source_key=_SOURCE_KEY,
                            source_case_id=ref.source_case_id,
                            sanitized_filename=detail.photo_filename,
                        )
                        if result is None:
                            placeholders_skipped += 1
                        else:
                            photo_local_path, photo_sha256 = result
                            photos_downloaded += 1
                    except (FetchTooLarge, Exception) as exc:
                        logger.info(
                            "Charles photo fetch failed for %s: %r",
                            ref.source_case_id,
                            exc,
                        )
                        photos_failed += 1

                _insert_raw_row(
                    session,
                    table_ident=table_ident,
                    dataset_version_id=context.dataset_version_id,
                    ref=ref,
                    detail_narrative=detail.narrative_text,
                    photo_filename=detail.photo_filename,
                    photo_alt_text=detail.photo_alt_text,
                    photo_source_url=detail.photo_url,
                    photo_sha256=photo_sha256,
                    photo_local_path=str(photo_local_path) if photo_local_path else None,
                )
                rows_inserted += 1
                if rows_inserted % 5 == 0:
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
            "Charles raw load: %d rows -> %s; photos %d downloaded, %d placeholders, %d failed",
            rows_inserted,
            table_ident,
            photos_downloaded,
            placeholders_skipped,
            photos_failed,
        )

    if rows_inserted < 3:
        raise RuntimeError(f"Charles raw load produced only {rows_inserted} rows; expected >= 3.")


def _content_type_from_filename(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_md_charles_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id    INT NOT NULL,
        source_case_id        TEXT NOT NULL,
        case_name             TEXT NOT NULL,
        detail_url            TEXT NOT NULL,
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
    ref: CaseRef,
    detail_narrative: str,
    photo_filename: str | None,
    photo_alt_text: str | None,
    photo_source_url: str | None,
    photo_sha256: str | None,
    photo_local_path: str | None,
) -> None:
    photo_ct = _content_type_from_filename(photo_filename)
    session.execute(
        text(f"""
            INSERT INTO {table_ident} (
                dataset_version_id, source_case_id, case_name, detail_url, narrative_text,
                photo_filename, photo_content_type, photo_alt_text,
                photo_source_url, photo_sha256, photo_local_path
            )
            VALUES (
                :dv, :scid, :name, :url, :narr,
                :pf, :pct, :pat, :psu, :psha, :plp
            )
            ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
        """),
        {
            "dv": dataset_version_id,
            "scid": ref.source_case_id,
            "name": ref.case_name,
            "url": ref.detail_url,
            "narr": detail_narrative,
            "pf": photo_filename,
            "pct": photo_ct,
            "pat": photo_alt_text,
            "psu": photo_source_url,
            "psha": photo_sha256,
            "plp": photo_local_path,
        },
    )

"""Raw-load stage for the BCounty adapter.

Fetches each detail page via polite_http, parses fields via scrape.py,
downloads the primary photo to data/photos/, and inserts one row per
case into raw_cold_case.cold_case_md_baltimore_county_dv<N>.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.adapters.cold_case_md_baltimore_county.scrape import (
    DetailPageFields,
    parse_detail_page,
)
from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
    download_case_photo,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import (
    FetchTooLarge,
    PoliteHTTPClient,
    RobotsTxtDisallowed,
)

logger = logging.getLogger(__name__)


def load_bcounty_raw(context: PipelineContext) -> None:
    """Fetch all detail pages + photos; write rows into raw schema."""
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set (run register_source first).")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    polite = context.get_metadata("polite_http")
    if not isinstance(polite, PoliteHTTPClient):
        raise TypeError("polite_http metadata is not a PoliteHTTPClient.")

    detail_urls: list[tuple[str, str]] = context.get_metadata("bcounty_detail_urls")
    if not detail_urls:
        raise RuntimeError("bcounty_detail_urls missing from context metadata.")

    table_ident = _raw_table_name(context.dataset_version_id)
    rows_inserted = 0
    photos_downloaded = 0
    photos_failed = 0

    with session_factory() as session:
        try:
            session.execute(text(_create_raw_table_sql(table_ident)))
            session.execute(
                text(f"DELETE FROM {table_ident} WHERE dataset_version_id = :dv"),
                {"dv": context.dataset_version_id},
            )
            session.commit()

            for detail_url, source_case_id in detail_urls:
                try:
                    response = polite.get(detail_url)
                except RobotsTxtDisallowed:
                    raise
                except Exception as exc:
                    logger.warning("BCounty detail fetch failed for %s: %r", source_case_id, exc)
                    continue

                try:
                    fields = parse_detail_page(response.text, base_url=detail_url)
                except ValueError as exc:
                    logger.warning(
                        "BCounty detail parse failed for %s: %s",
                        source_case_id,
                        exc,
                    )
                    continue

                photo_path: Path | None = None
                photo_sha256: str | None = None
                if fields.photo_source_url and fields.photo_filename:
                    try:
                        result = download_case_photo(
                            polite,
                            fields.photo_source_url,
                            source_key="cold_case_md_baltimore_county",
                            source_case_id=source_case_id,
                            sanitized_filename=fields.photo_filename,
                        )
                        if result is not None:
                            photo_path, photo_sha256 = result
                            photos_downloaded += 1
                    except (FetchTooLarge, Exception) as exc:
                        logger.info(
                            "BCounty photo fetch failed for %s: %r",
                            source_case_id,
                            exc,
                        )
                        photos_failed += 1

                _insert_raw_row(
                    session,
                    table_ident=table_ident,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=source_case_id,
                    detail_url=detail_url,
                    fields=fields,
                    photo_sha256=photo_sha256,
                    photo_local_path=str(photo_path) if photo_path else None,
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
            "BCounty raw load: %d rows -> %s; photos %d downloaded, %d failed",
            rows_inserted,
            table_ident,
            photos_downloaded,
            photos_failed,
        )

    # Sanity floor: assert the live page returned a meaningful number of cases.
    if rows_inserted < 50:
        raise RuntimeError(
            f"BCounty raw load produced only {rows_inserted} rows; expected >= 50."
            f" Source page may have changed structure."
        )


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_md_baltimore_county_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id    INT NOT NULL,
        source_case_id        TEXT NOT NULL,
        detail_url            TEXT NOT NULL,
        case_name             TEXT NOT NULL,
        case_year             INT,
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
    source_case_id: str,
    detail_url: str,
    fields: DetailPageFields,
    photo_sha256: str | None,
    photo_local_path: str | None,
) -> None:
    session.execute(
        text(f"""
            INSERT INTO {table_ident} (
                dataset_version_id, source_case_id, detail_url,
                case_name, case_year, narrative_text,
                photo_filename, photo_content_type, photo_alt_text,
                photo_source_url, photo_sha256, photo_local_path
            )
            VALUES (
                :dataset_version_id, :source_case_id, :detail_url,
                :case_name, :case_year, :narrative_text,
                :photo_filename, :photo_content_type, :photo_alt_text,
                :photo_source_url, :photo_sha256, :photo_local_path
            )
            """),
        {
            "dataset_version_id": dataset_version_id,
            "source_case_id": source_case_id,
            "detail_url": detail_url,
            "case_name": fields.case_name,
            "case_year": fields.case_year,
            "narrative_text": fields.narrative_text,
            "photo_filename": fields.photo_filename,
            "photo_content_type": fields.photo_content_type,
            "photo_alt_text": fields.photo_alt_text,
            "photo_source_url": fields.photo_source_url,
            "photo_sha256": photo_sha256,
            "photo_local_path": photo_local_path,
        },
    )

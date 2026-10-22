"""NH raw_load: fetch detail pages + photos, insert raw rows."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.adapters.cold_case_nh_doj.scrape_detail import (
    is_placeholder_photo,
    parse_detail,
)
from casesignal.etl.adapters.cold_case_nh_doj.scrape_index import IndexRecord
from casesignal.etl.services.photo_helpers import (
    PHOTO_EXT_BY_CONTENT_TYPE as _PHOTO_EXT_BY_CONTENT_TYPE,
)
from casesignal.etl.services.photo_helpers import (
    safe_filename as _safe_filename,
)
from casesignal.etl.services.photo_helpers import (
    sha256_of_file as _sha256_of_file,
)
from casesignal.etl.services.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

_PHOTO_DIR_ROOT = Path("data/photos/cold_case_nh_doj")


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_nh_doj_dv{dataset_version_id}"


def _ensure_table(session: Session, dataset_version_id: int) -> str:
    table = _raw_table_name(dataset_version_id)
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            dataset_version_id INTEGER NOT NULL,
            source_case_id     TEXT NOT NULL,
            title              TEXT,
            slug               TEXT,
            category_label     TEXT NOT NULL,
            year_tag           TEXT,
            town_tag           TEXT,
            age_tag            TEXT,
            narrative          TEXT,
            photo_filename     TEXT,
            photo_content_type TEXT,
            photo_alt_text     TEXT,
            photo_sha256       TEXT,
            photo_source_url   TEXT,
            source_detail_url  TEXT NOT NULL,
            PRIMARY KEY (dataset_version_id, source_case_id)
        )
    """))
    session.commit()
    return table


def load_nh_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    rows: list[IndexRecord] = context.get_metadata("nh_index_rows") or []
    if not rows:
        raise RuntimeError("nh_index_rows missing; prepare_input must run first.")

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
            "NH raw_load requires either context.session (test path) or "
            "context.metadata['session_factory'] (pipeline-runner path)."
        )

    dvid = context.dataset_version_id
    table = _ensure_table(session, dvid)

    inserted = 0
    failed = 0
    photos_fetched = 0
    photos_skipped_placeholder = 0
    photos_failed = 0

    for ir in rows:
        try:
            resp = polite.get(ir.detail_url)
            d = parse_detail(resp.text)

            source_case_id = f"nh-{ir.slug}"
            photo_filename: str | None = None
            photo_ct: str | None = None
            photo_sha: str | None = None
            photo_src_abs: str | None = None

            if d.photo_src and not is_placeholder_photo(d.photo_src):
                photo_url = urljoin(ir.detail_url, d.photo_src)
                photo_src_abs = photo_url
                try:
                    photo_resp = polite.get(photo_url)
                    raw_ct = (
                        photo_resp.headers.get("Content-Type", "")
                        .split(";")[0].strip().lower()
                    )
                    ext = _PHOTO_EXT_BY_CONTENT_TYPE.get(raw_ct)
                    if ext is None:
                        logger.warning(
                            "NH photo unrecognized Content-Type %r for %s; skipping",
                            raw_ct, photo_url,
                        )
                        photos_failed += 1
                    else:
                        photo_dir = _PHOTO_DIR_ROOT / source_case_id
                        photo_dir.mkdir(parents=True, exist_ok=True)
                        url_basename = (
                            urlparse(photo_url).path.rsplit("/", 1)[-1] or "photo"
                        )
                        fname = _safe_filename(url_basename)
                        if not fname.endswith(f".{ext}"):
                            fname = f"{fname}.{ext}"
                        dest = photo_dir / fname
                        dest.write_bytes(photo_resp.content)
                        photo_filename = fname
                        photo_ct = raw_ct
                        photo_sha = _sha256_of_file(dest)
                        photos_fetched += 1
                except Exception as exc:
                    logger.warning("NH photo fetch failed %s: %r", photo_url, exc)
                    photos_failed += 1
            elif d.photo_src and is_placeholder_photo(d.photo_src):
                photos_skipped_placeholder += 1

            session.execute(
                text(f"""
                    INSERT INTO {table} (
                        dataset_version_id, source_case_id, title, slug,
                        category_label, year_tag, town_tag, age_tag,
                        narrative, photo_filename, photo_content_type,
                        photo_alt_text, photo_sha256, photo_source_url,
                        source_detail_url
                    )
                    VALUES (
                        :dv, :scid, :title, :slug,
                        :cat, :year, :town, :age,
                        :narr, :pfn, :pct,
                        :palt, :psha, :psrc,
                        :url
                    )
                    ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
                """),
                {
                    "dv": dvid,
                    "scid": source_case_id,
                    "title": ir.title,
                    "slug": ir.slug,
                    "cat": ir.category_label,
                    "year": ir.year_tag,
                    "town": ir.town_tag,
                    "age": ir.age_tag,
                    "narr": d.narrative,
                    "pfn": photo_filename,
                    "pct": photo_ct,
                    "palt": d.photo_alt,
                    "psha": photo_sha,
                    "psrc": photo_src_abs,
                    "url": ir.detail_url,
                },
            )
            inserted += 1
        except Exception as exc:
            failed += 1
            logger.warning("NH detail load failed %s: %r", ir.detail_url, exc)

    session.commit()
    if owns_session:
        session.close()

    if context.logger is not None:
        context.logger.info(
            "NH raw_load: inserted=%d failed=%d photos_fetched=%d "
            "placeholder_skipped=%d photos_failed=%d (of %d)",
            inserted, failed, photos_fetched,
            photos_skipped_placeholder, photos_failed, len(rows),
        )

    context.increment_row_count("load_raw", inserted)

    if inserted < 100 and len(rows) >= 100:
        raise RuntimeError(
            f"NH raw_load inserted only {inserted} rows out of {len(rows)}; refusing."
        )

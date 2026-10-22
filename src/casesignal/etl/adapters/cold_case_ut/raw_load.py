"""Raw-load stage for the UT BCI adapter.

Per SitemapEntry from prepare_input:
  1. Polite GET detail page → parse_detail_page → DetailContents
  2. Filter: case_type != "unsolvedhomicide" → tally skipped_wrong_type
     (BCI does NOT publish a structured Case Status field — solved cases
     are removed from publication, so anything in the sitemap is effectively
     open. No status-classifier filter is needed.)
  3. Photo fetches: for each PhotoRef, polite.get() then write to disk
     after Content-Type allowlist check (jpeg/png/gif/webp only).
  4. Write raw row with all detail fields + photo metadata JSON.

Photo Content-Type allowlist is duplicated from cold_case_co/raw_load.py
rather than imported — keeps per-adapter coupling minimal and avoids a
cross-state shared module that would need to evolve carefully.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.adapters.cold_case_ut.scrape_detail import parse_detail_page
from casesignal.etl.adapters.cold_case_ut.scrape_sitemap import SitemapEntry
from casesignal.etl.services.photo_helpers import (
    PHOTO_EXT_BY_CONTENT_TYPE as _PHOTO_EXT_BY_CONTENT_TYPE,
)
from casesignal.etl.services.photo_helpers import (
    sha256_of_file as _sha256_of_file,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient

logger = logging.getLogger(__name__)


_SOURCE_KEY = "cold_case_ut"


def _photos_root() -> Path:
    return Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos"))


def load_ut_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    polite = context.get_metadata("polite_http")
    if not isinstance(polite, PoliteHTTPClient):
        raise TypeError("polite_http metadata is not a PoliteHTTPClient.")

    entries: list[SitemapEntry] = context.get_metadata("ut_sitemap_entries") or []
    if not entries:
        raise RuntimeError("ut_sitemap_entries missing; prepare_input must run first.")

    table_ident = _raw_table_name(context.dataset_version_id)

    cases_ingested = 0
    skipped_wrong_type = 0
    skipped_parse_error = 0
    skipped_missing_required = 0
    photos_fetched = 0
    photos_failed = 0

    payloads: list[dict[str, Any]] = []

    for entry in entries:
        try:
            resp = polite.get(entry.detail_url)
            slug = entry.detail_url.rstrip("/").rsplit("/", 1)[-1]
            detail = parse_detail_page(resp.text, slug=slug)
        except Exception as exc:
            logger.warning(
                "UT detail-page fetch/parse failed for %s: %r",
                entry.detail_url,
                exc,
            )
            skipped_parse_error += 1
            continue

        # Filter by case_type — only unsolvedhomicide ingests
        if (detail.case_type or "").lower() != "unsolvedhomicide":
            logger.info(
                "UT case %s skipped: case_type=%r != unsolvedhomicide",
                detail.slug,
                detail.case_type,
            )
            skipped_wrong_type += 1
            continue

        # Required-field gate (name + agency + at-least-one-date)
        any_date = any([detail.date_of_crime, detail.date_last_seen, detail.date_body_found])
        if not detail.name or not detail.agency_name or not any_date:
            logger.warning(
                "UT case %s skipped: missing required field (name=%r, agency=%r, any_date=%s)",
                detail.slug,
                detail.name,
                detail.agency_name,
                any_date,
            )
            skipped_missing_required += 1
            continue

        # Fetch photos with Content-Type allowlist
        photo_meta: list[dict[str, Any]] = []
        for photo in detail.photos:
            try:
                ct, local_path, sha = _fetch_photo(polite, photo.url, detail.slug, photo.n)
                if ct is None or local_path is None:
                    photos_failed += 1
                    continue
                photo_meta.append(
                    {
                        "n": photo.n,
                        "filename": local_path.name,
                        "content_type": ct,
                        "sha256": sha,
                        "source_url": photo.url,
                        "alt_text": photo.alt_text,
                    }
                )
                photos_fetched += 1
            except Exception as exc:
                logger.info(
                    "UT photo fetch failed slug=%s n=%d: %r",
                    detail.slug,
                    photo.n,
                    exc,
                )
                photos_failed += 1

        payloads.append(
            {
                "slug": detail.slug,
                "name": detail.name,
                "aliases": detail.aliases,
                "dob": detail.dob,
                "dod": detail.dod,
                "occupation": detail.occupation,
                "age": detail.age,
                "gender": detail.gender,
                "race": detail.race,
                "tribal_affiliation": detail.tribal_affiliation,
                "height": detail.height,
                "weight": detail.weight,
                "eye_color": detail.eye_color,
                "hair_color": detail.hair_color,
                "identifying_marks": detail.identifying_marks,
                "case_type": detail.case_type,
                "case_number": detail.case_number,
                "date_of_crime": detail.date_of_crime,
                "date_last_seen": detail.date_last_seen,
                "date_body_found": detail.date_body_found,
                "city": detail.city,
                "county": detail.county,
                "agency_name": detail.agency_name,
                "agency_phone": detail.agency_phone,
                "ncic_case_id": detail.ncic_case_id,
                "namus_case_id": detail.namus_case_id,
                "narrative": detail.narrative,
                "photos_json": json.dumps(photo_meta),
                "source_detail_url": entry.detail_url,
            }
        )
        cases_ingested += 1

    # Insert all raw rows in a single transaction
    with session_factory() as session:
        try:
            session.execute(text(_create_raw_table_sql(table_ident)))
            session.execute(
                text(f"DELETE FROM {table_ident} WHERE dataset_version_id = :dv"),
                {"dv": context.dataset_version_id},
            )
            session.commit()

            for p in payloads:
                _insert_raw_row(session, table_ident, context.dataset_version_id, p)
            session.commit()
            session.execute(text(f"ANALYZE {table_ident}"))
            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("load_raw", cases_ingested)
    if context.logger is not None:
        context.logger.info(
            "UT raw load: ingested=%d / skipped_wrong_type=%d "
            "/ skipped_parse=%d / skipped_required=%d; photos fetched=%d, failed=%d",
            cases_ingested,
            skipped_wrong_type,
            skipped_parse_error,
            skipped_missing_required,
            photos_fetched,
            photos_failed,
        )


def _fetch_photo(
    polite: PoliteHTTPClient,
    url: str,
    slug: str,
    n: int,
) -> tuple[str | None, Path | None, str]:
    """Polite-fetch one photo; return (content_type or None, local_path or None, sha256).

    Returns (None, None, "") if Content-Type is outside the allowlist — caller skips.
    """
    resp = polite.get(url)
    raw_ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    ext = _PHOTO_EXT_BY_CONTENT_TYPE.get(raw_ct)
    if ext is None:
        logger.warning(
            "UT photo slug=%s n=%d unrecognized Content-Type %r; skipping",
            slug,
            n,
            raw_ct,
        )
        return None, None, ""

    photo_dir = _photos_root() / _SOURCE_KEY / slug
    photo_dir.mkdir(parents=True, exist_ok=True)
    final_path = photo_dir / f"photo_{n}.{ext}"
    final_path.write_bytes(resp.content)
    sha = _sha256_of_file(final_path)
    return raw_ct, final_path, sha


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_ut_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id  INT  NOT NULL,
        slug                TEXT NOT NULL,
        name                TEXT NOT NULL,
        aliases             TEXT,
        dob                 TEXT,
        dod                 TEXT,
        occupation          TEXT,
        age                 TEXT,
        gender              TEXT,
        race                TEXT,
        tribal_affiliation  TEXT,
        height              TEXT,
        weight              TEXT,
        eye_color           TEXT,
        hair_color          TEXT,
        identifying_marks   TEXT,
        case_type           TEXT,
        case_number         TEXT,
        date_of_crime       TEXT,
        date_last_seen      TEXT,
        date_body_found     TEXT,
        city                TEXT,
        county              TEXT,
        agency_name         TEXT,
        agency_phone        TEXT,
        ncic_case_id        TEXT,
        namus_case_id       TEXT,
        narrative           TEXT,
        photos_json         TEXT,
        source_detail_url   TEXT,
        PRIMARY KEY (dataset_version_id, slug)
    )
    """


def _insert_raw_row(
    session: Session,
    table_ident: str,
    dataset_version_id: int,
    payload: dict[str, Any],
) -> None:
    p = dict(payload)
    p["dataset_version_id"] = dataset_version_id
    columns = list(p.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    column_list = ", ".join(columns)
    session.execute(
        text(f"""
            INSERT INTO {table_ident} ({column_list})
            VALUES ({placeholders})
            ON CONFLICT (dataset_version_id, slug) DO NOTHING
        """),
        p,
    )

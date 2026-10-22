"""Raw-load stage for the CO CBI adapter.

Per SearchResultRow from prepare_input:
  1. Polite GET detail page → parse_detail_page → DetailContents
  2. Drop if Case Type != Homicide or Case Status not in (OPEN, "")
  3. Photo fetches: for each PhotoRef, polite.get() then write to disk
     after Content-Type allowlist check (jpeg/png/gif/webp only)
  4. Write raw row with all detail fields + photo metadata JSON
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.adapters.cold_case_co.scrape_detail import parse_detail_page
from casesignal.etl.adapters.cold_case_co.scrape_search import SearchResultRow
from casesignal.etl.services.photo_helpers import (
    PHOTO_EXT_BY_CONTENT_TYPE as _PHOTO_EXT_BY_CONTENT_TYPE,
)
from casesignal.etl.services.photo_helpers import (
    sha256_of_file as _sha256_of_file,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient

logger = logging.getLogger(__name__)


_SOURCE_KEY = "cold_case_co"


def _photos_root() -> Path:
    return Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos"))


def load_co_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    polite = context.get_metadata("polite_http")
    if not isinstance(polite, PoliteHTTPClient):
        raise TypeError("polite_http metadata is not a PoliteHTTPClient.")

    rows: list[SearchResultRow] = context.get_metadata("co_search_rows") or []
    if not rows:
        raise RuntimeError("co_search_rows missing; prepare_input must run first.")

    table_ident = _raw_table_name(context.dataset_version_id)

    cases_ingested = 0
    cases_skipped_status_changed = 0
    cases_skipped_parse_error = 0
    photos_fetched = 0
    photos_failed = 0

    payloads: list[dict[str, Any]] = []

    for r in rows:
        try:
            resp = polite.get(r.detail_url)
            detail = parse_detail_page(
                resp.text,
                detail_id=r.detail_id,
                base_url=r.detail_url,
            )
        except Exception as exc:
            logger.warning(
                "CO detail-page fetch/parse failed for id=%d (%s): %r",
                r.detail_id,
                r.name,
                exc,
            )
            cases_skipped_parse_error += 1
            continue

        # Drift detection: case_type / case_status moved between search and detail
        if (detail.case_type or "").lower() != "homicide":
            logger.info(
                "CO case id=%d (%s) skipped: case_type=%r != Homicide",
                r.detail_id,
                r.name,
                detail.case_type,
            )
            cases_skipped_status_changed += 1
            continue
        if (detail.case_status or "").upper() not in ("OPEN", ""):
            # CBI sometimes leaves Case Status blank — accept "" as still in scope
            logger.info(
                "CO case id=%d (%s) skipped: status=%r not OPEN",
                r.detail_id,
                r.name,
                detail.case_status,
            )
            cases_skipped_status_changed += 1
            continue

        # Fetch photos with Content-Type allowlist
        photo_meta: list[dict[str, Any]] = []
        for photo in detail.photos:
            try:
                ct, local_path, sha = _fetch_photo(polite, photo.url, r.detail_id, photo.n)
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
                    "CO photo fetch failed id=%d n=%d: %r",
                    r.detail_id,
                    photo.n,
                    exc,
                )
                photos_failed += 1

        payloads.append(
            {
                "detail_id": r.detail_id,
                "name": detail.name,
                "aliases": detail.aliases,
                "dob": detail.dob,
                "dod": detail.dod,
                "occupation": detail.occupation,
                "age": detail.age,
                "gender": detail.gender,
                "race": detail.race,
                "ethnicity": detail.ethnicity,
                "tribal_affiliation": detail.tribal_affiliation,
                "height": detail.height,
                "weight": detail.weight,
                "eye_color": detail.eye_color,
                "hair_color": detail.hair_color,
                "identifying_marks": detail.identifying_marks,
                "case_type": detail.case_type,
                "case_status": detail.case_status,
                "incident_date": detail.incident_date,
                "agency": detail.agency,
                "agency_case_id": detail.agency_case_id,
                "judicial_district": detail.judicial_district,
                "city": detail.city,
                "county": detail.county,
                "namus_case_id": detail.namus_case_id,
                "ncmec_case_id": detail.ncmec_case_id,
                "narrative": detail.narrative,
                "photos_json": json.dumps(photo_meta),
                "source_detail_url": r.detail_url,
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
            "CO raw load: ingested=%d / skipped_status=%d / skipped_parse=%d; "
            "photos fetched=%d, failed=%d",
            cases_ingested,
            cases_skipped_status_changed,
            cases_skipped_parse_error,
            photos_fetched,
            photos_failed,
        )

    # Drift gate (same threshold as Gate 3 in verify script: 5% silent-pass band)
    baseline = context.get_metadata("co_baseline_count") or 0
    floor = int(baseline * 0.95)
    if cases_ingested < floor:
        raise RuntimeError(
            f"CO load_raw produced only {cases_ingested} rows; "
            f"expected >= {floor} (5% silent-pass band of baseline {baseline})."
        )


def _fetch_photo(
    polite: PoliteHTTPClient,
    url: str,
    detail_id: int,
    n: int,
) -> tuple[str | None, Path | None, str]:
    """Polite-fetch one photo; return (content_type or None, local_path or None, sha256).

    Returns (None, None, "") if Content-Type is outside the allowlist — caller skips.

    Uses polite.get() (not fetch_to_file) because we need the Content-Type
    header to choose the on-disk extension before writing. CO photos at /large
    are <1MB each; in-memory is fine.
    """
    resp = polite.get(url)
    raw_ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    ext = _PHOTO_EXT_BY_CONTENT_TYPE.get(raw_ct)
    if ext is None:
        logger.warning(
            "CO photo id=%d n=%d unrecognized Content-Type %r; skipping",
            detail_id,
            n,
            raw_ct,
        )
        return None, None, ""

    photo_dir = _photos_root() / _SOURCE_KEY / str(detail_id)
    photo_dir.mkdir(parents=True, exist_ok=True)
    final_path = photo_dir / f"photo_{n}.{ext}"
    final_path.write_bytes(resp.content)
    sha = _sha256_of_file(final_path)
    return raw_ct, final_path, sha


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_co_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id  INT  NOT NULL,
        detail_id           INT  NOT NULL,
        name                TEXT NOT NULL,
        aliases             TEXT,
        dob                 TEXT,
        dod                 TEXT,
        occupation          TEXT,
        age                 TEXT,
        gender              TEXT,
        race                TEXT,
        ethnicity           TEXT,
        tribal_affiliation  TEXT,
        height              TEXT,
        weight              TEXT,
        eye_color           TEXT,
        hair_color          TEXT,
        identifying_marks   TEXT,
        case_type           TEXT,
        case_status         TEXT,
        incident_date       TEXT,
        agency              TEXT,
        agency_case_id      TEXT,
        judicial_district   TEXT,
        city                TEXT,
        county              TEXT,
        namus_case_id       TEXT,
        ncmec_case_id       TEXT,
        narrative           TEXT,
        photos_json         TEXT,
        source_detail_url   TEXT,
        PRIMARY KEY (dataset_version_id, detail_id)
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
            ON CONFLICT (dataset_version_id, detail_id) DO NOTHING
        """),
        p,
    )

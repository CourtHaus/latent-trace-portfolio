"""OH raw_load: fetch detail pages + photos, insert raw rows."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.adapters.cold_case_oh_ag.scrape_detail import parse_detail
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

_PHOTO_DIR_ROOT = Path("data/photos/cold_case_oh_ag")


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_oh_ag_dv{dataset_version_id}"


def _ensure_table(session: Session, dataset_version_id: int) -> str:
    """Create raw_cold_case.cold_case_oh_ag_dv<N> if it doesn't exist."""
    table = _raw_table_name(dataset_version_id)
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            dataset_version_id INTEGER NOT NULL,
            case_number        TEXT,
            name               TEXT,
            aliases            TEXT,
            dob                TEXT,
            gender             TEXT,
            race               TEXT,
            height             TEXT,
            weight_lbs         INTEGER,
            hair_color         TEXT,
            eye_color          TEXT,
            incident_date      TEXT,
            address            TEXT,
            city               TEXT,
            county             TEXT,
            agency             TEXT,
            narrative          TEXT,
            photos_json        TEXT,
            source_detail_url  TEXT NOT NULL,
            PRIMARY KEY (dataset_version_id, source_detail_url)
        )
    """))
    session.commit()
    return table


def load_oh_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    rows = context.get_metadata("oh_search_rows") or []
    if not rows:
        raise RuntimeError("oh_search_rows missing; prepare_input must run first.")

    polite = context.get_metadata("polite_http")
    if polite is None:
        raise RuntimeError("polite_http metadata missing; prepare_input must run first.")

    # Prefer the pipeline runner's session_factory (production path); fall
    # back to context.session if a caller has injected one (e.g., the
    # integration test). Mirrors CO/UT raw_load.
    session_factory = context.get_metadata("session_factory")
    if session_factory is not None:
        session = session_factory()
        owns_session = True
    elif context.session is not None:
        session = context.session
        owns_session = False
    else:
        raise RuntimeError(
            "OH raw_load requires either context.session (test path) or "
            "context.metadata['session_factory'] (pipeline-runner path)."
        )

    dvid = context.dataset_version_id
    table = _ensure_table(session, dvid)

    inserted = 0
    failed = 0
    photos_fetched = 0
    photos_failed = 0

    for sr in rows:
        try:
            resp = polite.get(sr.detail_url)
            d = parse_detail(resp.text, source_url=sr.detail_url)

            # Download photos
            photo_records: list[dict[str, Any]] = []
            if d.photos:
                case_id_safe = _safe_filename(d.case_number or sr.detail_url.rsplit("/", 1)[-1])
                photo_dir = _PHOTO_DIR_ROOT / case_id_safe
                photo_dir.mkdir(parents=True, exist_ok=True)

                for idx, p in enumerate(d.photos):
                    photo_url = urljoin(sr.detail_url, p.src)
                    try:
                        photo_resp = polite.get(photo_url)
                        raw_ct = (
                            photo_resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                        )
                        ext = _PHOTO_EXT_BY_CONTENT_TYPE.get(raw_ct)
                        if ext is None:
                            logger.warning(
                                "OH photo unrecognized Content-Type %r for %s; skipping",
                                raw_ct,
                                photo_url,
                            )
                            photos_failed += 1
                            continue

                        fname = _safe_filename(f"{idx:02d}_{p.src.rsplit('/', 1)[-1]}")
                        if not fname.endswith(f".{ext}"):
                            fname = f"{fname}.{ext}"
                        dest = photo_dir / fname

                        dest.write_bytes(photo_resp.content)
                        sha = _sha256_of_file(dest)
                        photo_records.append(
                            {
                                "filename": fname,
                                "alt": p.alt,
                                "is_primary": p.is_primary,
                                "sha256": sha,
                                "source_url": photo_url,
                                "content_type": raw_ct,
                            }
                        )
                        photos_fetched += 1
                    except Exception as exc:
                        logger.warning(
                            "OH photo fetch failed %s: %r",
                            photo_url,
                            exc,
                        )
                        photos_failed += 1

            session.execute(
                text(f"""
                    INSERT INTO {table} (
                        dataset_version_id, case_number, name, aliases, dob,
                        gender, race, height, weight_lbs, hair_color, eye_color,
                        incident_date, address, city, county, agency,
                        narrative, photos_json, source_detail_url
                    )
                    VALUES (
                        :dv, :case_number, :name, :aliases, :dob,
                        :gender, :race, :height, :weight_lbs,
                        :hair_color, :eye_color,
                        :incident_date, :address, :city, :county, :agency,
                        :narrative, :photos_json, :source_url
                    )
                    ON CONFLICT (dataset_version_id, source_detail_url) DO NOTHING
                """),
                {
                    "dv": dvid,
                    "case_number": d.case_number,
                    "name": d.name,
                    "aliases": d.aliases,
                    "dob": d.dob,
                    "gender": d.gender,
                    "race": d.race,
                    "height": d.height,
                    "weight_lbs": d.weight_lbs,
                    "hair_color": d.hair_color,
                    "eye_color": d.eye_color,
                    "incident_date": d.incident_date,
                    "address": d.address,
                    "city": d.city,
                    "county": d.county,
                    "agency": d.agency,
                    "narrative": d.narrative,
                    "photos_json": json.dumps(photo_records),
                    "source_url": sr.detail_url,
                },
            )
            inserted += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "OH detail load failed %s: %r",
                sr.detail_url,
                exc,
            )

    session.commit()
    if owns_session:
        session.close()

    if context.logger is not None:
        context.logger.info(
            "OH raw_load: inserted=%d failed=%d photos_fetched=%d photos_failed=%d " "(of %d rows)",
            inserted,
            failed,
            photos_fetched,
            photos_failed,
            len(rows),
        )
    else:
        logger.info(
            "OH raw_load: inserted=%d failed=%d photos_fetched=%d photos_failed=%d " "(of %d rows)",
            inserted,
            failed,
            photos_fetched,
            photos_failed,
            len(rows),
        )

    context.increment_row_count("load_raw", inserted)

    if inserted < 50 and len(rows) >= 50:
        raise RuntimeError(
            f"OH raw_load inserted only {inserted} rows out of {len(rows)}; " "refusing to proceed."
        )

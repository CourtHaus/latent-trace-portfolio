"""Raw-load stage for DC MPDC adapter.

Per year_page (already filtered in prepare_input):
  1. Polite GET → scrape_year.parse_year_page → list[CaseStub]
  2. Filter to stubs whose date_string parses to an in-scope year
     (handles grouped year-pages like 1971-1990 where we may want only
     a subset)
  3. Per stub:
     a. Polite GET on detail_url → scrape_detail.parse_detail_page →
        DetailContents (narrative + pdf_url)
     b. Polite fetch on pdf_url → save to data/photos/cold_case_dc_mpdc/
        <ccn>/flier.pdf
     c. pdf_parser.parse_flier(local_pdf_path) → FlierContents
        (CCN + photo bytes + detectives + reward + bulletin no.)
     d. If PDF photo extraction failed, fall back to fetching the
        index thumbnail
     e. Save photo bytes to disk; compute SHA256
  4. Insert raw row.

source_case_id strategy: prefer CCN (e.g., 22-057-404). If CCN extraction
failed, fall back to slug + date pattern with collision disambiguation
post-pass.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.adapters.cold_case_dc_mpdc.pdf_parser import FlierContents, parse_flier
from casesignal.etl.adapters.cold_case_dc_mpdc.scrape_detail import parse_detail_page
from casesignal.etl.adapters.cold_case_dc_mpdc.scrape_year import CaseStub, parse_year_page
from casesignal.etl.services.photo_helpers import (
    sha256_of_bytes,
)
from casesignal.etl.services.photo_helpers import (
    sha256_of_file as _sha256_of_file,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import FetchTooLarge, PoliteHTTPClient

logger = logging.getLogger(__name__)


_SOURCE_KEY = "cold_case_dc_mpdc"


def _photos_root() -> Path:
    return Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos"))


def load_dc_mpdc_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set (run register_source first).")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    polite = context.get_metadata("polite_http")
    if not isinstance(polite, PoliteHTTPClient):
        raise TypeError("polite_http metadata is not a PoliteHTTPClient.")

    year_pages: list[tuple[frozenset[int], str]] = context.get_metadata("dc_year_pages") or []
    if not year_pages:
        raise RuntimeError("dc_year_pages missing from context.")
    in_scope: set[int] = context.get_metadata("dc_in_scope_years") or set()

    table_ident = _raw_table_name(context.dataset_version_id)
    rows: list[dict[str, Any]] = []
    photos_downloaded = 0
    photos_failed = 0
    photos_via_thumbnail = 0
    ccn_extracted = 0

    # Walk each year_page, fetch + parse
    for _year_set, year_url in year_pages:
        try:
            response = polite.get(year_url)
            stubs = parse_year_page(response.text, base_url=year_url)
        except Exception as exc:
            logger.warning("DC MPDC year-page fetch failed for %s: %r", year_url, exc)
            continue

        # Filter to stubs whose date is in_scope (handles grouped year-pages)
        filtered = [s for s in stubs if _stub_year_in_scope(s, in_scope)]
        if not filtered:
            continue

        for stub in filtered:
            try:
                row = _process_stub(polite, stub)
            except Exception as exc:
                logger.warning("DC MPDC stub processing failed for %s: %r", stub.name, exc)
                continue

            rows.append(row)
            if row["photo_sha256"]:
                if row.get("_photo_via") == "thumbnail":
                    photos_via_thumbnail += 1
                else:
                    photos_downloaded += 1
            else:
                photos_failed += 1
            if row["ccn"]:
                ccn_extracted += 1

    # Disambiguate source_case_ids that collide
    rows = _disambiguate_source_case_ids(rows)

    # Insert all raw rows in a single transaction
    with session_factory() as session:
        try:
            session.execute(text(_create_raw_table_sql(table_ident)))
            session.execute(
                text(f"DELETE FROM {table_ident} WHERE dataset_version_id = :dv"),
                {"dv": context.dataset_version_id},
            )
            session.commit()

            for r in rows:
                _insert_raw_row(
                    session,
                    table_ident=table_ident,
                    dataset_version_id=context.dataset_version_id,
                    row=r,
                )
            session.commit()
            session.execute(text(f"ANALYZE {table_ident}"))
            session.commit()
        except Exception:
            session.rollback()
            raise

    rows_inserted = len(rows)
    context.increment_row_count("load_raw", rows_inserted)
    if context.logger is not None:
        context.logger.info(
            "DC MPDC raw load: %d rows -> %s; photos %d via PDF, %d via thumbnail, %d failed; CCN extracted for %d",
            rows_inserted,
            table_ident,
            photos_downloaded,
            photos_via_thumbnail,
            photos_failed,
            ccn_extracted,
        )

    # NOTE: 2020 has ~119 unsolved cases (verified C2). Floor is 100, not 150 from plan.
    if rows_inserted < 100:
        raise RuntimeError(
            f"DC MPDC raw load produced only {rows_inserted} rows; expected >= 100 for 2020."
        )


def _stub_year_in_scope(stub: CaseStub, in_scope: set[int]) -> bool:
    """Return True if the stub's date falls within in_scope years.

    Returns True (include) if date can't be parsed (better to ingest +
    log than silently drop).
    """
    if not stub.date_string:
        return True
    year = _extract_year(stub.date_string)
    if year is None:
        return True
    return year in in_scope


def _extract_year(date_string: str) -> int | None:
    m = re.search(r"\b(19|20)\d{2}\b", date_string)
    if m is None:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def _process_stub(
    polite: PoliteHTTPClient,
    stub: CaseStub,
) -> dict[str, Any]:
    """Fetch detail + PDF for one stub; return a raw row dict."""
    # Fetch detail page
    detail_resp = polite.get(stub.detail_url)
    detail = parse_detail_page(detail_resp.text, base_url=stub.detail_url)

    narrative = detail.narrative
    if not narrative:
        # Fallback narrative built from year-page stub
        loc = stub.location or "an undisclosed location"
        date = stub.date_string or "an unknown date"
        narrative = f"{stub.name} was killed in {loc} on {date}."

    # Fetch + parse PDF
    flier: FlierContents | None = None
    pdf_local_path: Path | None = None
    if detail.pdf_url:
        try:
            # Stash PDF to disk in photos dir (we keep it for audit)
            slug = _slugify(stub.name)
            pdf_dir = _photos_root() / _SOURCE_KEY / "fliers" / slug
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_local_path = pdf_dir / "flier.pdf"
            polite.fetch_to_file(detail.pdf_url, pdf_local_path)
            flier = parse_flier(pdf_local_path)
        except (FetchTooLarge, Exception) as exc:
            logger.info("DC MPDC PDF fetch/parse failed for %s: %r", stub.name, exc)

    if flier is None:
        flier = FlierContents(
            ccn=None,
            public_bulletin_no=None,
            photo_bytes=None,
            photo_content_type=None,
            detective_contacts=[],
            reward_amount=None,
        )

    # source_case_id: CCN if available, else slug+date pattern
    if flier.ccn:
        source_case_id = flier.ccn
    else:
        date_iso = _date_to_iso(stub.date_string) or "undated"
        source_case_id = f"{_slugify(stub.name)}-{date_iso}"

    # Save photo to disk: prefer PDF-extracted, fall back to thumbnail
    photo_local_path: Path | None = None
    photo_filename: str | None = None
    photo_sha256: str | None = None
    photo_content_type: str | None = None
    photo_via = None

    if flier.photo_bytes:
        ext = _ext_for_content_type(flier.photo_content_type or "image/jpeg")
        photo_filename = f"{_safe_id(source_case_id)}{ext}"
        photo_dir = _photos_root() / _SOURCE_KEY / source_case_id
        photo_dir.mkdir(parents=True, exist_ok=True)
        photo_local_path = photo_dir / photo_filename
        photo_local_path.write_bytes(flier.photo_bytes)
        photo_sha256 = sha256_of_bytes(flier.photo_bytes)
        photo_content_type = flier.photo_content_type
        photo_via = "pdf"
    elif stub.thumb_url:
        try:
            ext = _ext_from_url(stub.thumb_url) or ".jpg"
            photo_filename = f"{_safe_id(source_case_id)}_thumb{ext}"
            photo_dir = _photos_root() / _SOURCE_KEY / source_case_id
            photo_dir.mkdir(parents=True, exist_ok=True)
            photo_local_path = photo_dir / photo_filename
            polite.fetch_to_file(stub.thumb_url, photo_local_path)
            photo_sha256 = _sha256_of_file(photo_local_path)
            photo_content_type = _content_type_from_filename(photo_filename)
            photo_via = "thumbnail"
        except (FetchTooLarge, Exception) as exc:
            logger.info("DC MPDC thumbnail fetch failed for %s: %r", stub.name, exc)

    return {
        "source_case_id": source_case_id,
        "ccn": flier.ccn,
        "case_name": stub.name,
        "incident_date_string": stub.date_string,
        "incident_date_iso": _date_to_iso(stub.date_string),
        "incident_address": stub.location,
        "narrative": narrative,
        "photo_filename": photo_filename,
        "photo_content_type": photo_content_type,
        "photo_sha256": photo_sha256,
        "photo_local_path": str(photo_local_path) if photo_local_path else None,
        "pdf_filename": pdf_local_path.name if pdf_local_path else None,
        "pdf_local_path": str(pdf_local_path) if pdf_local_path else None,
        "detective_contacts_json": json.dumps([asdict(c) for c in flier.detective_contacts]),
        "reward_amount": flier.reward_amount,
        "public_bulletin_no": flier.public_bulletin_no,
        "source_detail_url": stub.detail_url,
        "source_pdf_url": detail.pdf_url,
        "_photo_via": photo_via,  # internal — stripped before insert
    }


def _disambiguate_source_case_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append `-2`, `-3`, etc. to colliding source_case_ids."""
    counts = Counter(r["source_case_id"] for r in rows)
    seen: dict[str, int] = {}
    out = []
    for r in rows:
        sid = r["source_case_id"]
        if counts[sid] > 1:
            seen[sid] = seen.get(sid, 0) + 1
            if seen[sid] > 1:
                r = dict(r)
                r["source_case_id"] = f"{sid}-{seen[sid]}"
        out.append(r)
    return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s or "unknown"


def _safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text)


def _date_to_iso(date_string: str | None) -> str | None:
    if not date_string:
        return None
    # Try common formats observed on MPDC year-pages
    for fmt in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%b. %d, %Y",
        "%m/%d/%Y",
        "%-m/%-d/%Y",
    ):
        try:
            return datetime.strptime(date_string.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    # Last resort: extract just the year
    m = re.search(r"\b(19|20)\d{2}\b", date_string)
    if m:
        return f"{m.group(0)}-01-01"
    return None


def _ext_for_content_type(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(content_type, ".bin")


def _ext_from_url(url: str) -> str | None:
    m = re.search(r"\.(jpg|jpeg|png|gif|webp)(?:\?|$)", url, re.IGNORECASE)
    return f".{m.group(1).lower()}" if m else None


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
    return f"raw_cold_case.cold_case_dc_mpdc_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id    INT NOT NULL,
        source_case_id        TEXT NOT NULL,
        ccn                   TEXT,
        case_name             TEXT NOT NULL,
        incident_date_string  TEXT,
        incident_date_iso     TEXT,
        incident_address      TEXT,
        narrative             TEXT NOT NULL,
        photo_filename        TEXT,
        photo_content_type    TEXT,
        photo_sha256          TEXT,
        photo_local_path      TEXT,
        pdf_filename          TEXT,
        pdf_local_path        TEXT,
        detective_contacts_json  TEXT,
        reward_amount         INTEGER,
        public_bulletin_no    TEXT,
        source_detail_url     TEXT,
        source_pdf_url        TEXT,
        PRIMARY KEY (dataset_version_id, source_case_id)
    )
    """


def _insert_raw_row(
    session: Session,
    *,
    table_ident: str,
    dataset_version_id: int,
    row: dict[str, Any],
) -> None:
    # Drop the internal _photo_via key before inserting
    payload = {k: v for k, v in row.items() if not k.startswith("_")}
    payload["dataset_version_id"] = dataset_version_id
    columns = list(payload.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    column_list = ", ".join(columns)
    session.execute(
        text(f"""
            INSERT INTO {table_ident} ({column_list})
            VALUES ({placeholders})
            ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
        """),
        payload,
    )

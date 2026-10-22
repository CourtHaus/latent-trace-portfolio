"""Raw-load stage for the MN BCA adapter.

Per harvest record:
  1. Fetch + parse the SOC PDF (deduped by URL -- 92 distinct of 96 records;
     parsed SocContents cached so a shared multi-victim PDF is parsed once).
  2. Fetch the victim photo (Picture1), per record.
  3. Insert one raw row into raw_cold_case.cold_case_mn_bca_dv<N>.

PDFs and photos are static assets on portal.dps.mn.gov and pass the
Imperva WAF cookieless.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.adapters.cold_case_mn_bca.pdf_parser import SocContents, parse_soc_pdf
from casesignal.etl.adapters.cold_case_mn_bca.read_harvest import HarvestRecord
from casesignal.etl.services.photo_helpers import (
    PHOTO_EXT_BY_CONTENT_TYPE,
    safe_filename,
    sha256_of_file,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient

logger = logging.getLogger(__name__)

_PHOTO_DIR_ROOT = Path("data/photos/cold_case_mn_bca")


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_mn_bca_dv{dataset_version_id}"


def _ensure_table(session: Session, dataset_version_id: int) -> str:
    table = _raw_table_name(dataset_version_id)
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            dataset_version_id  INTEGER NOT NULL,
            source_case_id      TEXT NOT NULL,
            name_first          TEXT,
            name_middle         TEXT,
            name_last           TEXT,
            name_suffix         TEXT,
            age                 TEXT,
            incident_date       TEXT,
            date_of_birth       TEXT,
            location_city       TEXT,
            location_county     TEXT,
            location_state      TEXT,
            pdf_url             TEXT NOT NULL,
            narrative           TEXT,
            pdf_sex             TEXT,
            pdf_race            TEXT,
            contact_agency      TEXT,
            contact_phone       TEXT,
            reward              INTEGER,
            photo_filename      TEXT,
            photo_content_type  TEXT,
            photo_sha256        TEXT,
            photo_source_url    TEXT,
            PRIMARY KEY (dataset_version_id, source_case_id)
        )
    """))
    session.commit()
    return table


def load_mn_raw(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    records: list[HarvestRecord] = context.get_metadata("mn_harvest_records") or []
    if not records:
        raise RuntimeError("mn_harvest_records missing; prepare_input must run first.")

    polite = context.get_metadata("polite_http")
    if polite is None:
        raise RuntimeError("polite_http metadata missing; prepare_input must run first.")

    meta = (context.get_metadata("source_definition", {}) or {}).get("metadata", {}) or {}
    portal_origin = meta.get("portal_origin", "https://portal.dps.mn.gov")

    session_factory = context.get_metadata("session_factory")
    if session_factory is not None:
        session = session_factory()
        owns_session = True
    elif context.session is not None:
        session = context.session
        owns_session = False
    else:
        raise RuntimeError(
            "MN raw_load requires context.session (test path) or "
            "context.metadata['session_factory'] (pipeline-runner path)."
        )

    dvid = context.dataset_version_id
    table = _ensure_table(session, dvid)

    soc_cache: dict[str, SocContents] = {}
    inserted = 0
    pdf_failed = 0
    photos_fetched = 0
    photos_failed = 0

    for rec in records:
        pdf_url = portal_origin + rec.pdf_path
        soc = soc_cache.get(pdf_url)
        if soc is None:
            soc = _fetch_and_parse_pdf(polite, pdf_url)
            soc_cache[pdf_url] = soc
            if not soc.narrative:
                pdf_failed += 1

        photo = _fetch_photo(polite, rec, portal_origin)
        if photo is not None:
            photos_fetched += 1
        elif rec.picture_path:
            photos_failed += 1

        session.execute(
            text(f"""
                INSERT INTO {table} (
                    dataset_version_id, source_case_id,
                    name_first, name_middle, name_last, name_suffix,
                    age, incident_date, date_of_birth,
                    location_city, location_county, location_state,
                    pdf_url, narrative, pdf_sex, pdf_race,
                    contact_agency, contact_phone, reward,
                    photo_filename, photo_content_type, photo_sha256, photo_source_url
                )
                VALUES (
                    :dv, :scid,
                    :nf, :nm, :nl, :ns,
                    :age, :date, :dob,
                    :city, :county, :state,
                    :pdf_url, :narrative, :sex, :race,
                    :agency, :phone, :reward,
                    :pfn, :pct, :psha, :psrc
                )
                ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
            """),
            {
                "dv": dvid,
                "scid": rec.source_case_id,
                "nf": rec.name_first,
                "nm": rec.name_middle,
                "nl": rec.name_last,
                "ns": rec.name_suffix,
                "age": rec.age,
                "date": rec.incident_date_iso,
                "dob": rec.date_of_birth,
                "city": rec.location_city,
                "county": rec.location_county,
                "state": rec.location_state,
                "pdf_url": pdf_url,
                # narrative is str (never None); coerce an empty parse to NULL
                "narrative": soc.narrative or None,
                "sex": soc.sex,
                "race": soc.race,
                "agency": soc.contact_agency,
                "phone": soc.contact_phone,
                "reward": rec.reward,
                "pfn": photo["filename"] if photo else None,
                "pct": photo["content_type"] if photo else None,
                "psha": photo["sha256"] if photo else None,
                "psrc": photo["source_url"] if photo else None,
            },
        )
        inserted += 1

    session.commit()
    if owns_session:
        session.close()

    context.increment_row_count("load_raw", inserted)
    log = context.logger or logger
    log.info(
        "MN raw_load: inserted=%d (%d distinct PDFs, %d distinct PDF parse failures), "
        "photos_fetched=%d photos_failed=%d",
        inserted,
        len(soc_cache),
        pdf_failed,
        photos_fetched,
        photos_failed,
    )

    if len(records) >= 80 and inserted < 80:
        raise RuntimeError(
            f"MN raw_load inserted only {inserted} rows out of {len(records)}; refusing to proceed."
        )


def _fetch_and_parse_pdf(polite: PoliteHTTPClient, pdf_url: str) -> SocContents:
    """Fetch a SOC PDF to a temp file and parse it. Never raises."""
    try:
        resp = polite.get(pdf_url)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(resp.content)
            tmp.flush()
            return parse_soc_pdf(Path(tmp.name))
    except Exception as exc:  # noqa: BLE001 -- a bad PDF must not abort the run
        logger.warning("MN PDF fetch/parse failed for %s: %r", pdf_url, exc)
        return SocContents(
            narrative="", sex=None, race=None, contact_agency=None, contact_phone=None
        )


def _fetch_photo(
    polite: PoliteHTTPClient, rec: HarvestRecord, portal_origin: str
) -> dict[str, str] | None:
    """Fetch the victim photo to disk. Returns photo metadata or None."""
    if not rec.picture_path:
        return None
    photo_url = portal_origin + rec.picture_path
    try:
        resp = polite.get(photo_url)
        raw_ct = (resp.headers.get("Content-Type", "").split(";")[0].strip().lower())
        ext = PHOTO_EXT_BY_CONTENT_TYPE.get(raw_ct)
        if ext is None:
            logger.warning("MN photo unrecognized Content-Type %r for %s", raw_ct, photo_url)
            return None
        photo_dir = _PHOTO_DIR_ROOT / safe_filename(rec.source_case_id)
        photo_dir.mkdir(parents=True, exist_ok=True)
        filename = safe_filename(f"{rec.source_case_id}.{ext}")
        dest = photo_dir / filename
        dest.write_bytes(resp.content)
        return {
            "filename": filename,
            "content_type": raw_ct,
            "sha256": sha256_of_file(dest),
            "source_url": photo_url,
        }
    except Exception as exc:  # noqa: BLE001 -- a bad photo must not abort the run
        logger.warning("MN photo fetch failed %s: %r", photo_url, exc)
        return None

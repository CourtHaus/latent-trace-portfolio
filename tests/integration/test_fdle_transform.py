"""Integration tests for the FL FDLE transform stage.

Validates that transform_fl routes real incident addresses to cold_case.cases,
agency addresses to cold_case.contact, synthesizes case names correctly, enqueues
both Tier-1 and Tier-2 extraction jobs, and only enqueues geocoding jobs when an
incident address is present.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


# ---------------------------------------------------------------------------
# Raw-table DDL — mirrors the updated raw_load schema (includes agency_address)
# ---------------------------------------------------------------------------
_RAW_DDL = """
CREATE TABLE {table} (
    dataset_version_id INTEGER NOT NULL,
    source_case_id     TEXT NOT NULL,
    case_title         TEXT,
    victim_name        TEXT,
    case_type          TEXT,
    incident_date      TEXT,
    incident_address   TEXT,
    incident_city      TEXT,
    agency_address     TEXT,
    reporting_agency   TEXT,
    agency_phone       TEXT,
    gender             TEXT,
    race               TEXT,
    height             TEXT,
    weight_lbs         INTEGER,
    dob                TEXT,
    narrative          TEXT,
    photos_json        TEXT,
    source_detail_url  TEXT NOT NULL,
    PRIMARY KEY (dataset_version_id, source_case_id)
)
"""

_RAW_COLS = [
    "dataset_version_id",
    "source_case_id",
    "case_title",
    "victim_name",
    "case_type",
    "incident_date",
    "incident_address",
    "incident_city",
    "agency_address",
    "reporting_agency",
    "agency_phone",
    "gender",
    "race",
    "height",
    "weight_lbs",
    "dob",
    "narrative",
    "photos_json",
    "source_detail_url",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sf(db_engine: Any) -> Any:
    from casesignal.etl.services.db import create_session_factory

    return create_session_factory(db_engine)


@pytest.fixture
def fdle_corpus(sf: Any) -> Any:
    """Seed the minimal ETL bookkeeping rows (source_system + dataset_version +
    ingestion_run) for the FDLE transform tests. Yields the dataset_version_id.
    Teardown removes all canonical + raw rows.
    """
    from tests.integration._seed import seed_corpus

    # Unique source_code per fixture invocation to avoid collisions between tests
    # or if a previous run left rows behind.
    source_code = f"FDLE_TX_{uuid.uuid4().hex[:8].upper()}"

    # seed_corpus seeds cold_case.cases rows too — we pass an empty list so it
    # only creates the bookkeeping rows we need.  transform_fl will then DELETE
    # whatever is there for that dv and re-insert from raw, so no case rows are
    # needed up front.
    corpus = seed_corpus(sf, source_code=source_code, cases=[])
    dv = corpus.dataset_version_id
    table = f"raw_cold_case.cold_case_fl_fdle_dv{dv}"

    try:
        with sf() as s:
            s.execute(text(_RAW_DDL.format(table=table)))
            s.commit()
        yield corpus
    finally:
        with sf() as s:
            # Remove any canonical rows that transform may have written (FK order matters)
            case_subquery = (
                "case_id IN (SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
            )
            for child in (
                "geocoding_job",
                "extraction_job",
                "case_extractions",
                "case_photo",
                "victim",
                "contact",
            ):
                s.execute(
                    text(f"DELETE FROM cold_case.{child} WHERE {case_subquery}"),
                    {"dv": dv},
                )
            s.execute(text("DELETE FROM cold_case.cases WHERE dataset_version_id = :dv"), {"dv": dv})
            s.execute(text(f"DROP TABLE IF EXISTS {table}"))
            s.commit()
        corpus.teardown()


def _insert_raw(sf: Any, dv: int, row: dict[str, Any]) -> None:
    """Insert one row into the FL FDLE raw table for dv."""
    table = f"raw_cold_case.cold_case_fl_fdle_dv{dv}"
    col_list = ", ".join(_RAW_COLS)
    param_list = ", ".join(f":{c}" for c in _RAW_COLS)
    values = {"dataset_version_id": dv, **{c: row.get(c) for c in _RAW_COLS if c != "dataset_version_id"}}
    with sf() as s:
        s.execute(text(f"INSERT INTO {table} ({col_list}) VALUES ({param_list})"), values)
        s.commit()


def _make_context(corpus: Any, sf: Any) -> Any:
    from casesignal.etl.services.pipeline_context import PipelineContext

    ctx = PipelineContext(
        source_key="cold_case_fl_fdle_transform_test",
        source_code="FDLE_TRANSFORM_TEST",
        source_name="FL FDLE Transform Test",
        source_family="cold_case",
        source_year=2026,
        source_state="FL",
        source_path=Path("/dev/null"),
        logger=logging.getLogger("test_fdle_transform"),
    )
    ctx.dataset_version_id = corpus.dataset_version_id
    ctx.set_metadata("session_factory", sf)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_transform_full_record(fdle_corpus: Any, sf: Any) -> None:
    """Full raw record: real incident address, populated case_title, agency info.

    Asserts:
    - cases.address == incident_address; address_source == 'source'; city IS NULL
    - contact.address == agency_address
    - case_name == case_title (title takes priority)
    - exactly 2 extraction_job rows (Tier-1 AND Tier-2)
    - at least 1 geocoding_job row
    """
    from casesignal.etl.adapters.cold_case_fl_fdle.transform import transform_fl

    dv = fdle_corpus.dataset_version_id
    _insert_raw(
        sf,
        dv,
        {
            "source_case_id": "FL-FULL-001",
            "case_title": "Avery Exampleton Homicide (Alachua CSO)",
            "victim_name": "Exampleton, Avery",
            "case_type": "Homicide",
            "incident_date": "01-15-1995",
            "incident_address": "101 Example Lane GAINESVILLE FL",
            "incident_city": None,
            "agency_address": "202 Sample Avenue",
            "reporting_agency": "Alachua CSO",
            "agency_phone": "2025550101",
            "gender": "Female",
            "race": None,
            "height": None,
            "weight_lbs": None,
            "dob": None,
            "narrative": "Avery Exampleton was found deceased at her residence.",
            "photos_json": "[]",
            "source_detail_url": "https://web.fdle.state.fl.us/unsolvedcases/public/caseDetails.jsf",
        },
    )

    ctx = _make_context(fdle_corpus, sf)
    transform_fl(ctx)

    with sf() as session:
        case_row = session.execute(
            text("""
                SELECT case_id, case_name, address, city, address_source
                  FROM cold_case.cases
                 WHERE dataset_version_id = :dv
            """),
            {"dv": dv},
        ).first()
        assert case_row is not None, "expected 1 case row after transform"
        assert (
            case_row.address == "101 Example Lane GAINESVILLE FL"
        ), f"address should be incident address, got {case_row.address!r}"
        assert case_row.address_source == "source", (
            f"address_source should be 'source', got {case_row.address_source!r}"
        )
        assert case_row.city is None, f"city should be NULL (incident_city was None), got {case_row.city!r}"
        assert case_row.case_name == "Avery Exampleton Homicide (Alachua CSO)", (
            f"case_name should be case_title, got {case_row.case_name!r}"
        )

        case_id = case_row.case_id

        contact = session.execute(
            text("SELECT address FROM cold_case.contact WHERE case_id = :c"),
            {"c": case_id},
        ).first()
        assert contact is not None, "expected 1 contact row"
        assert contact.address == "202 Sample Avenue", (
            f"contact.address should be agency_address, got {contact.address!r}"
        )

        extraction_count = session.execute(
            text("SELECT COUNT(*) FROM cold_case.extraction_job WHERE case_id = :c"),
            {"c": case_id},
        ).scalar_one()
        assert extraction_count == 2, (
            f"expected exactly 2 extraction jobs (Tier-1 + Tier-2), got {extraction_count}"
        )

        tier1_count = session.execute(
            text("SELECT COUNT(*) FROM cold_case.extraction_job WHERE case_id = :c AND prompt_tier = 1"),
            {"c": case_id},
        ).scalar_one()
        assert tier1_count == 1, f"expected 1 Tier-1 job, got {tier1_count}"

        tier2_count = session.execute(
            text("SELECT COUNT(*) FROM cold_case.extraction_job WHERE case_id = :c AND prompt_tier = 2"),
            {"c": case_id},
        ).scalar_one()
        assert tier2_count == 1, f"expected 1 Tier-2 job, got {tier2_count}"

        geocoding_count = session.execute(
            text("SELECT COUNT(*) FROM cold_case.geocoding_job WHERE case_id = :c"),
            {"c": case_id},
        ).scalar_one()
        assert geocoding_count >= 1, f"expected >=1 geocoding job (address present), got {geocoding_count}"


def test_transform_sparse_record(fdle_corpus: Any, sf: Any) -> None:
    """Sparse raw record: no incident_address, no case_title, no victim_name, sentinel agency_address.

    Asserts:
    - cases.address IS NULL; address_source IS NULL
    - case_name starts with 'Unidentified'
    - exactly 2 extraction_job rows (Tier-1 + Tier-2)
    - ZERO geocoding_job rows (no address to geocode)
    """
    from casesignal.etl.adapters.cold_case_fl_fdle.transform import transform_fl

    dv = fdle_corpus.dataset_version_id
    _insert_raw(
        sf,
        dv,
        {
            "source_case_id": "FL-SPARSE-001",
            "case_title": None,
            "victim_name": None,
            "case_type": "Homicide",
            "incident_date": None,
            "incident_address": None,
            "incident_city": None,
            # Sentinel agency_address — clean_sentinel should return None
            "agency_address": ",",
            "reporting_agency": "Unknown Agency",
            "agency_phone": None,
            "gender": None,
            "race": None,
            "height": None,
            "weight_lbs": None,
            "dob": None,
            "narrative": "",
            "photos_json": "[]",
            "source_detail_url": "https://web.fdle.state.fl.us/unsolvedcases/public/caseDetails.jsf",
        },
    )

    ctx = _make_context(fdle_corpus, sf)
    transform_fl(ctx)

    with sf() as session:
        case_row = session.execute(
            text("""
                SELECT case_id, case_name, address, address_source
                  FROM cold_case.cases
                 WHERE dataset_version_id = :dv
            """),
            {"dv": dv},
        ).first()
        assert case_row is not None, "expected 1 case row after transform"
        assert case_row.address is None, (
            f"address should be NULL for sparse record, got {case_row.address!r}"
        )
        assert case_row.address_source is None, (
            f"address_source should be NULL for sparse record, got {case_row.address_source!r}"
        )
        assert (case_row.case_name or "").startswith("Unidentified"), (
            f"case_name should start with 'Unidentified' for nameless sparse record, "
            f"got {case_row.case_name!r}"
        )

        case_id = case_row.case_id

        extraction_count = session.execute(
            text("SELECT COUNT(*) FROM cold_case.extraction_job WHERE case_id = :c"),
            {"c": case_id},
        ).scalar_one()
        assert extraction_count == 2, (
            f"expected exactly 2 extraction jobs (Tier-1 + Tier-2), got {extraction_count}"
        )

        geocoding_count = session.execute(
            text("SELECT COUNT(*) FROM cold_case.geocoding_job WHERE case_id = :c"),
            {"c": case_id},
        ).scalar_one()
        assert geocoding_count == 0, (
            f"expected ZERO geocoding jobs for sparse record (no address), got {geocoding_count}"
        )


def test_transform_leaked_title_record(fdle_corpus: Any, sf: Any) -> None:
    """Source quirk: the case summary is typed into the title field, narrative empty.

    The transform must NOT use the sentence as case_name (synthesize from the
    victim instead) and must route the sentence into the narrative so Tier-2 has
    text to extract. Confirmed against live FDLE source 1905 (Daniluk).
    """
    from casesignal.etl.adapters.cold_case_fl_fdle.transform import transform_fl

    leaked = "victim's nude body was discovered deceased in a road side ditch by passerby."
    dv = fdle_corpus.dataset_version_id
    _insert_raw(
        sf,
        dv,
        {
            "source_case_id": "FL-LEAKED-001",
            "case_title": leaked,
            "victim_name": "Daniluk, Andrea Denise",
            "case_type": "Homicide",
            "incident_address": None,
            "agency_address": ",",
            "narrative": "",
            "photos_json": "[]",
            "source_detail_url": "https://web.fdle.state.fl.us/unsolvedcases/public/caseDetails.jsf",
        },
    )

    ctx = _make_context(fdle_corpus, sf)
    transform_fl(ctx)

    with sf() as session:
        row = session.execute(
            text("SELECT case_name, about_text FROM cold_case.cases WHERE dataset_version_id = :dv"),
            {"dv": dv},
        ).first()
        assert row is not None
        assert row.case_name == "Andrea Denise Daniluk — Homicide", (
            f"leaked sentence must not be the case_name, got {row.case_name!r}"
        )
        assert row.about_text == leaked, (
            f"leaked title should fall back into the narrative, got {row.about_text!r}"
        )

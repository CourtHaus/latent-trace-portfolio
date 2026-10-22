"""Integration tests for the OK OSBI transform stage.

Validates that transform_ok routes rows correctly: homicide with an explicit
"<County> County" mention in the narrative resolves source_county_fips +
geocoding address; a missing_person row with only a city mentioned (no
"County" token) leaves county fields NULL/state-only; case_type mapping
covers suspicious_death.
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
# Raw-table DDL — mirrors the OK OSBI raw_load schema (Task 8)
# ---------------------------------------------------------------------------
_RAW_DDL = """
CREATE TABLE {table} (
    dataset_version_id INTEGER NOT NULL,
    source_case_id     TEXT NOT NULL,
    name                TEXT NOT NULL,
    case_name           TEXT NOT NULL,
    case_type           TEXT,
    date_text           TEXT,
    incident_date_iso   TEXT,
    narrative           TEXT,
    contact_text        TEXT,
    source_range_url    TEXT,
    photos_json         TEXT,
    PRIMARY KEY (dataset_version_id, source_case_id)
)
"""

_RAW_COLS = [
    "dataset_version_id",
    "source_case_id",
    "name",
    "case_name",
    "case_type",
    "date_text",
    "incident_date_iso",
    "narrative",
    "contact_text",
    "source_range_url",
    "photos_json",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sf(db_engine: Any) -> Any:
    from casesignal.etl.services.db import create_session_factory

    return create_session_factory(db_engine)


@pytest.fixture
def ok_corpus(sf: Any) -> Any:
    """Seed the minimal ETL bookkeeping rows (source_system + dataset_version +
    ingestion_run) for the OK OSBI transform tests, plus 3 seeded raw rows
    matching the module's test bodies. Yields the seeded corpus (use
    .dataset_version_id). Teardown removes all canonical + raw rows.
    """
    from tests.integration._seed import seed_corpus

    source_code = f"OK_OSBI_TX_{uuid.uuid4().hex[:8].upper()}"

    corpus = seed_corpus(sf, source_code=source_code, cases=[])
    dv = corpus.dataset_version_id
    table = f"raw_cold_case.cold_case_ok_osbi_dv{dv}"

    try:
        with sf() as s:
            s.execute(text(_RAW_DDL.format(table=table)))
            s.commit()

        _insert_raw(
            sf,
            dv,
            {
                "source_case_id": "james-middle-example-1984-11-15",
                "name": "James Middle Example",
                "case_name": "James Middle Example",
                "case_type": "homicide",
                "date_text": "November 15, 1984",
                "incident_date_iso": "1984-11-15",
                "narrative": (
                    "James Middle Example' remains were found in Pottawatomie County. "
                    "James had been shot in the head."
                ),
                "contact_text": (
                    "Anyone with information is asked to please contact the OSBI via "
                    "email cold.case@osbi.ok.gov"
                ),
                "source_range_url": "https://osbi.ok.gov/coldcases/a-b",
                "photos_json": (
                    '[{"filename": "photo.jpg", "content_type": "image/jpeg", '
                    '"sha256": "abc123", "source_url": "https://example.com/photo.jpg"}]'
                ),
            },
        )
        _insert_raw(
            sf,
            dv,
            {
                "source_case_id": "casey-e-sampler-2004-10-23",
                "name": "Casey E. Sampler",
                "case_name": "Casey E. Sampler",
                "case_type": "missing_person",
                "date_text": "October 23, 2004",
                "incident_date_iso": "2004-10-23",
                "narrative": "Casey E. Sampler was last seen in Geronimo, Oklahoma.",
                "contact_text": None,
                "source_range_url": "https://osbi.ok.gov/coldcases/a-b",
                "photos_json": "[]",
            },
        )
        _insert_raw(
            sf,
            dv,
            {
                "source_case_id": "john-suspicious-2010-01-01",
                "name": "John Suspicious",
                "case_name": "John Suspicious",
                "case_type": "suspicious_death",
                "date_text": "January 1, 2010",
                "incident_date_iso": "2010-01-01",
                "narrative": "John Suspicious was found deceased under unusual circumstances.",
                "contact_text": None,
                "source_range_url": "https://osbi.ok.gov/coldcases/s-u",
                "photos_json": "[]",
            },
        )

        yield corpus
    finally:
        with sf() as s:
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
    """Insert one row into the OK OSBI raw table for dv."""
    table = f"raw_cold_case.cold_case_ok_osbi_dv{dv}"
    col_list = ", ".join(_RAW_COLS)
    param_list = ", ".join(f":{c}" for c in _RAW_COLS)
    values = {"dataset_version_id": dv, **{c: row.get(c) for c in _RAW_COLS if c != "dataset_version_id"}}
    with sf() as s:
        s.execute(text(f"INSERT INTO {table} ({col_list}) VALUES ({param_list})"), values)
        s.commit()


def _make_context(corpus: Any, sf: Any) -> Any:
    from casesignal.etl.services.pipeline_context import PipelineContext

    ctx = PipelineContext(
        source_key="cold_case_ok_osbi_transform_test",
        source_code="OK_OSBI_TRANSFORM_TEST",
        source_name="OK OSBI Transform Test",
        source_family="cold_case",
        source_year=2026,
        source_state="OK",
        source_path=Path("/dev/null"),
        logger=logging.getLogger("test_ok_osbi_transform"),
    )
    ctx.dataset_version_id = corpus.dataset_version_id
    ctx.set_metadata("session_factory", sf)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_transform_homicide_with_county(ok_corpus: Any, sf: Any) -> None:
    from casesignal.etl.adapters.cold_case_ok_osbi.transform import transform_ok

    transform_ok(_make_context(ok_corpus, sf))

    with sf() as s:
        case = s.execute(text(
            "SELECT case_id, case_type, state, incident_date, source_county_fips, about_text "
            "FROM cold_case.cases WHERE dataset_version_id=:dv AND source_case_id='james-middle-example-1984-11-15'"
        ), {"dv": ok_corpus.dataset_version_id}).one()
        assert case.case_type == "homicide"
        assert case.state == "OK"
        assert str(case.incident_date) == "1984-11-15"
        assert case.source_county_fips == "40125"  # Pottawatomie
        assert "shot in the head" in case.about_text
        assert "please contact" not in case.about_text  # contact not in extraction text

        victim = s.execute(text(
            "SELECT first_name, last_name, gender, race, age_num, race_source "
            "FROM cold_case.victim WHERE case_id=:cid"
        ), {"cid": case.case_id}).one()
        assert (victim.first_name, victim.last_name) == ("James Middle", "Example")
        assert victim.gender is None and victim.race is None and victim.race_source is None

        contact = s.execute(text(
            "SELECT email FROM cold_case.contact WHERE case_id=:cid"
        ), {"cid": case.case_id}).one()
        assert contact.email == "cold.case@osbi.ok.gov"

        jobs = s.execute(text(
            "SELECT prompt_tier FROM cold_case.extraction_job WHERE case_id=:cid ORDER BY prompt_tier"
        ), {"cid": case.case_id}).scalars().all()
        assert jobs == [1, 2]

        geo = s.execute(text(
            "SELECT address_text, county_fips FROM cold_case.geocoding_job WHERE case_id=:cid"
        ), {"cid": case.case_id}).one()
        assert geo.address_text == "Pottawatomie County, OK"
        assert geo.county_fips == "40125"


def test_transform_missing_person_city_only_no_county(ok_corpus: Any, sf: Any) -> None:
    from casesignal.etl.adapters.cold_case_ok_osbi.transform import transform_ok

    transform_ok(_make_context(ok_corpus, sf))

    with sf() as s:
        case = s.execute(text(
            "SELECT case_id, case_type, source_county_fips FROM cold_case.cases "
            "WHERE dataset_version_id=:dv AND source_case_id='casey-e-sampler-2004-10-23'"
        ), {"dv": ok_corpus.dataset_version_id}).one()
        assert case.case_type == "missing_person"
        assert case.source_county_fips is None  # no county mention
        geo = s.execute(text(
            "SELECT address_text, county_fips FROM cold_case.geocoding_job WHERE case_id=:cid"
        ), {"cid": case.case_id}).one()
        assert geo.address_text == "Oklahoma"
        assert geo.county_fips is None


def test_transform_suspicious_death_type(ok_corpus: Any, sf: Any) -> None:
    from casesignal.etl.adapters.cold_case_ok_osbi.transform import transform_ok

    transform_ok(_make_context(ok_corpus, sf))

    with sf() as s:
        ct = s.execute(text(
            "SELECT case_type FROM cold_case.cases WHERE dataset_version_id=:dv "
            "AND source_case_id='john-suspicious-2010-01-01'"
        ), {"dv": ok_corpus.dataset_version_id}).scalar_one()
        assert ct == "suspicious_death"

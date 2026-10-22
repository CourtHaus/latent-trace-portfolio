"""Integration tests for the AR ASP transform stage.

Validates that transform_ar routes full-field homicide rows correctly (case,
victim, contact, extraction jobs, county-FIPS geocoding job), tolerates sparse
missing_person rows (no sex/cause/photos, unknown county), and lands
multi-victim rows as ONE garbled victim row for Tier-2 roster reconciliation
to split later.
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
# Raw-table DDL — mirrors the AR ASP raw_load schema
# ---------------------------------------------------------------------------
_RAW_DDL = """
CREATE TABLE {table} (
    dataset_version_id INTEGER NOT NULL,
    source_case_id     TEXT NOT NULL,
    slug               TEXT NOT NULL,
    case_name          TEXT NOT NULL,
    case_type          TEXT,
    age_text           TEXT,
    race               TEXT,
    sex                TEXT,
    date_label         TEXT,
    date_text          TEXT,
    cause              TEXT,
    county             TEXT,
    case_number        TEXT,
    narrative          TEXT,
    contact_text       TEXT,
    contact_agency     TEXT,
    contact_phone      TEXT,
    photos_json        TEXT,
    source_detail_url  TEXT NOT NULL,
    PRIMARY KEY (dataset_version_id, source_case_id)
)
"""

_RAW_COLS = [
    "dataset_version_id",
    "source_case_id",
    "slug",
    "case_name",
    "case_type",
    "age_text",
    "race",
    "sex",
    "date_label",
    "date_text",
    "cause",
    "county",
    "case_number",
    "narrative",
    "contact_text",
    "contact_agency",
    "contact_phone",
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
def ar_corpus(sf: Any) -> Any:
    """Seed the minimal ETL bookkeeping rows (source_system + dataset_version +
    ingestion_run) for the AR ASP transform tests. Yields the seeded corpus
    (use .dataset_version_id). Teardown removes all canonical + raw rows.
    """
    from tests.integration._seed import seed_corpus

    # Unique source_code per fixture invocation to avoid collisions between tests
    # or if a previous run left rows behind.
    source_code = f"AR_TX_{uuid.uuid4().hex[:8].upper()}"

    # seed_corpus seeds cold_case.cases rows too — we pass an empty list so it
    # only creates the bookkeeping rows we need. transform_ar will then DELETE
    # whatever is there for that dv and re-insert from raw, so no case rows are
    # needed up front.
    corpus = seed_corpus(sf, source_code=source_code, cases=[])
    dv = corpus.dataset_version_id
    table = f"raw_cold_case.cold_case_ar_asp_dv{dv}"

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
    """Insert one row into the AR ASP raw table for dv."""
    table = f"raw_cold_case.cold_case_ar_asp_dv{dv}"
    col_list = ", ".join(_RAW_COLS)
    param_list = ", ".join(f":{c}" for c in _RAW_COLS)
    values = {"dataset_version_id": dv, **{c: row.get(c) for c in _RAW_COLS if c != "dataset_version_id"}}
    with sf() as s:
        s.execute(text(f"INSERT INTO {table} ({col_list}) VALUES ({param_list})"), values)
        s.commit()


def _make_context(corpus: Any, sf: Any) -> Any:
    from casesignal.etl.services.pipeline_context import PipelineContext

    ctx = PipelineContext(
        source_key="cold_case_ar_asp_transform_test",
        source_code="AR_ASP_TRANSFORM_TEST",
        source_name="AR ASP Transform Test",
        source_family="cold_case",
        source_year=2026,
        source_state="AR",
        source_path=Path("/dev/null"),
        logger=logging.getLogger("test_ar_asp_transform"),
    )
    ctx.dataset_version_id = corpus.dataset_version_id
    ctx.set_metadata("session_factory", sf)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_transform_full_homicide(ar_corpus: Any, sf: Any) -> None:
    """Full-field homicide row lands everywhere it should."""
    from casesignal.etl.adapters.cold_case_ar_asp.transform import transform_ar

    dv = ar_corpus.dataset_version_id
    _insert_raw(
        sf,
        dv,
        {
            "source_case_id": "SYN-001",
            "slug": "ada-ann-exampleton-example",
            "case_name": "Ada Ann Exampleton Example",
            "case_type": "homicide",
            "age_text": "76",
            "race": "White",
            "sex": "Female",
            "date_label": "death",
            "date_text": "January 14, 1991",
            "cause": "Strangulation in Association with Exposure",
            "county": "Washington",
            "case_number": "SYN-001",
            "narrative": (
                "On January 14, 1991, Ada Ann Exampleton Example was found deceased. "
                "She was pronounced dead at the hospital."
            ),
            "contact_text": None,
            "contact_agency": "ASP Company D",
            "contact_phone": "(202) 555-0100",
            "photos_json": (
                '[{"filename": "photo.jpg", "content_type": "image/jpeg", '
                '"sha256": "abc123", "source_url": "https://example.com/photo.jpg"}]'
            ),
            "source_detail_url": "https://www.ark.org/asp_coldcase/index.php/home/detail/SYN-001",
        },
    )

    ctx = _make_context(ar_corpus, sf)
    transform_ar(ctx)

    with sf() as s:
        case = s.execute(text(
            "SELECT case_id, case_name, case_type, state, incident_date, "
            "       source_county_fips, about_text, incident_date_source "
            "FROM cold_case.cases WHERE dataset_version_id = :dv AND source_case_id = 'SYN-001'"
        ), {"dv": ar_corpus.dataset_version_id}).one()
        assert case.case_type == "homicide"
        assert case.state == "AR"
        assert str(case.incident_date) == "1991-01-14"
        assert case.source_county_fips == "05143"
        assert case.incident_date_source == "source"
        # Cause line folded into stored source text (extraction offsets stay valid)
        assert case.about_text.endswith("Cause of death: Strangulation in Association with Exposure.")

        victim = s.execute(text(
            "SELECT first_name, last_name, gender, age_text, race, race_source, gender_source "
            "FROM cold_case.victim WHERE case_id = :cid"
        ), {"cid": case.case_id}).one()
        assert (victim.first_name, victim.last_name) == ("Ada Ann Exampleton", "Example")
        assert victim.gender == "F"
        assert victim.age_text == "76"
        assert victim.race == "White"
        assert victim.race_source == "source"
        assert victim.gender_source == "source"

        contact = s.execute(text(
            "SELECT last_name, phone FROM cold_case.contact WHERE case_id = :cid"
        ), {"cid": case.case_id}).one()
        assert contact.last_name == "ASP Company D"
        assert contact.phone == "(202) 555-0100"

        jobs = s.execute(text(
            "SELECT prompt_tier FROM cold_case.extraction_job WHERE case_id = :cid ORDER BY prompt_tier"
        ), {"cid": case.case_id}).scalars().all()
        assert jobs == [1, 2]

        geo = s.execute(text(
            "SELECT address_text, state_code, county_fips FROM cold_case.geocoding_job WHERE case_id = :cid"
        ), {"cid": case.case_id}).one()
        assert geo.address_text == "Washington County, AR"
        assert geo.state_code == "AR"
        assert geo.county_fips == "05143"


def test_transform_missing_person_and_sparse_fields(ar_corpus: Any, sf: Any) -> None:
    """DATE MISSING → missing_person; no SEX/CAUSE/photos tolerated;
    month-year date lands as day 1; unknown county → NULL fips but the
    geocoding job still carries the county text for the ladder."""
    from casesignal.etl.adapters.cold_case_ar_asp.transform import transform_ar

    dv = ar_corpus.dataset_version_id
    _insert_raw(
        sf,
        dv,
        {
            "source_case_id": "C36-152-79",
            "slug": "kay-collins",
            "case_name": "Robin Exampleton",
            "case_type": "missing_person",
            "age_text": None,
            "race": None,
            "sex": None,
            "date_label": "missing",
            "date_text": "December 1978",
            "cause": None,
            "county": "Nowhere",
            "case_number": "C36-152-79",
            "narrative": "Robin Exampleton was last seen.",
            "contact_text": None,
            "contact_agency": None,
            "contact_phone": None,
            "photos_json": "[]",
            "source_detail_url": "https://www.ark.org/asp_coldcase/index.php/home/detail/C36-152-79",
        },
    )

    ctx = _make_context(ar_corpus, sf)
    transform_ar(ctx)

    with sf() as s:
        case = s.execute(text(
            "SELECT case_id, case_type, incident_date, source_county_fips, about_text "
            "FROM cold_case.cases WHERE dataset_version_id = :dv AND source_case_id = 'C36-152-79'"
        ), {"dv": ar_corpus.dataset_version_id}).one()
        assert case.case_type == "missing_person"
        assert str(case.incident_date) == "1978-12-01"
        assert case.source_county_fips is None
        assert "Cause of death" not in case.about_text

        victim = s.execute(text(
            "SELECT gender, age_text FROM cold_case.victim WHERE case_id = :cid"
        ), {"cid": case.case_id}).one()
        assert victim.gender is None

        geo = s.execute(text(
            "SELECT address_text, county_fips FROM cold_case.geocoding_job WHERE case_id = :cid"
        ), {"cid": case.case_id}).one()
        assert geo.address_text == "Nowhere County, AR"
        assert geo.county_fips is None

        photos = s.execute(text(
            "SELECT count(*) FROM cold_case.case_photo WHERE case_id = :cid"
        ), {"cid": case.case_id}).scalar_one()
        assert photos == 0


def test_transform_multi_victim_single_garbled_row(ar_corpus: Any, sf: Any) -> None:
    """Multi-victim case inserts ONE victim row named from the case name;
    Tier-2 roster reconciliation is the sanctioned splitter (its garbled-row
    detection keys on ' and ' in the stored name)."""
    from casesignal.etl.adapters.cold_case_ar_asp.transform import transform_ar

    dv = ar_corpus.dataset_version_id
    _insert_raw(
        sf,
        dv,
        {
            "source_case_id": "CID-B-03522-04",
            "slug": "alf-and-bea-testford",
            "case_name": "Alf and Bea Testford",
            "case_type": "homicide",
            "age_text": "48 (SB) and 43 (DB)",
            "race": "White",
            "sex": None,
            "date_label": "death",
            "date_text": "November 16, 2004",
            "cause": "Gunshot",
            "county": "Calhoun",
            "case_number": "CID-B-03522-04",
            "narrative": "Alf and Bea Testford were found deceased at their home.",
            "contact_text": None,
            "contact_agency": None,
            "contact_phone": None,
            "photos_json": "[]",
            "source_detail_url": "https://www.ark.org/asp_coldcase/index.php/home/detail/CID-B-03522-04",
        },
    )

    ctx = _make_context(ar_corpus, sf)
    transform_ar(ctx)

    with sf() as s:
        case = s.execute(text(
            "SELECT case_id FROM cold_case.cases "
            "WHERE dataset_version_id = :dv AND source_case_id = 'CID-B-03522-04'"
        ), {"dv": ar_corpus.dataset_version_id}).one()
        victims = s.execute(text(
            "SELECT first_name, last_name, age_text, gender "
            "FROM cold_case.victim WHERE case_id = :cid"
        ), {"cid": case.case_id}).all()
        assert len(victims) == 1
        assert (victims[0].first_name, victims[0].last_name) == ("Alf and Bea", "Testford")
        assert victims[0].age_text == "48 (SB) and 43 (DB)"
        assert victims[0].gender is None

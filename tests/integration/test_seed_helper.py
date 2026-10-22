"""Self-test for the integration-test seed helper."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


def test_seed_corpus_inserts_and_tears_down(db_engine: Engine) -> None:
    from casesignal.etl.services.db import create_session_factory
    from tests.integration._seed import CaseSpec, VictimSpec, seed_corpus

    sf = create_session_factory(db_engine)
    corpus = seed_corpus(
        sf,
        source_code="SEED_HELPER_SELFTEST",
        cases=[
            CaseSpec(
                source_case_id="sh-1",
                case_name="Helper One",
                state="ZZ",
                city="Testville",
                incident_date="2010-06-01",
                latitude=39.0,
                longitude=-77.0,
                geocode_precision="street",
                victims=[VictimSpec(first_name="A", last_name="One", gender="M")],
            ),
        ],
    )
    try:
        assert corpus.dataset_version_id > 0
        assert "sh-1" in corpus.case_ids
        with sf() as s:
            n = s.execute(
                text("SELECT COUNT(*) FROM cold_case.cases WHERE dataset_version_id = :dv"),
                {"dv": corpus.dataset_version_id},
            ).scalar_one()
            assert n == 1
            has_geom = s.execute(
                text("SELECT geom IS NOT NULL FROM cold_case.cases WHERE case_id = :cid"),
                {"cid": corpus.case_ids["sh-1"]},
            ).scalar_one()
            assert has_geom is True
    finally:
        corpus.teardown()

    with sf() as s:
        leftover = s.execute(
            text("SELECT COUNT(*) FROM etl.source_system WHERE source_code = :c"),
            {"c": "SEED_HELPER_SELFTEST"},
        ).scalar_one()
        assert leftover == 0

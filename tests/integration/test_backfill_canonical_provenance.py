"""One-shot script tags existing rows' provenance as 'source' or 'tier2'."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scripts.backfill_canonical_provenance import run_backfill


@pytest.fixture
def seeded_cases(db_session: Session) -> Any:
    """Seed three cases with different provenance patterns."""
    # Setup: source_system + dataset_version
    db_session.execute(text("""
        INSERT INTO etl.source_system (source_code, source_name)
        VALUES ('TEST_PROV_BACKFILL', 'prov backfill test') ON CONFLICT DO NOTHING
    """))
    ssid = db_session.execute(
        text(
            "SELECT source_system_id FROM etl.source_system WHERE source_code='TEST_PROV_BACKFILL'"
        )
    ).scalar()
    dvid = db_session.execute(
        text("""
        INSERT INTO etl.dataset_version (source_system_id, source_year, source_label,
            source_hash, ingestion_status)
        VALUES (:ss, 2024, 'test-backfill', 'hb', 'draft') RETURNING dataset_version_id
    """),
        {"ss": ssid},
    ).scalar()

    # Case A: canonical address matches Tier-2 extracted → should tag 'tier2'
    cid_a = db_session.execute(
        text("""
        INSERT INTO cold_case.cases (dataset_version_id, source_case_id, case_name,
            case_type, slug, state, address, address_source)
        VALUES (:dv, 'A', 'A', 'homicide', 'a-bp-test', 'XX', '1 Main', NULL)
        RETURNING case_id
    """),
        {"dv": dvid},
    ).scalar()
    db_session.execute(
        text("""
        INSERT INTO cold_case.case_extractions (case_id, prompt_tier, extractor_version,
            prompt_hash, model_id, address_text)
        VALUES (:c, 2, 't', 'h', 'm', '1 Main')
    """),
        {"c": cid_a},
    )

    # Case B: canonical address differs from Tier-2 → should tag 'source'
    cid_b = db_session.execute(
        text("""
        INSERT INTO cold_case.cases (dataset_version_id, source_case_id, case_name,
            case_type, slug, state, address, address_source)
        VALUES (:dv, 'B', 'B', 'homicide', 'b-bp-test', 'XX', '2 Different', NULL)
        RETURNING case_id
    """),
        {"dv": dvid},
    ).scalar()
    db_session.execute(
        text("""
        INSERT INTO cold_case.case_extractions (case_id, prompt_tier, extractor_version,
            prompt_hash, model_id, address_text)
        VALUES (:c, 2, 't', 'h2', 'm', '99 Different Address')
    """),
        {"c": cid_b},
    )

    # Case C: canonical NULL → source stays NULL
    cid_c = db_session.execute(
        text("""
        INSERT INTO cold_case.cases (dataset_version_id, source_case_id, case_name,
            case_type, slug, state, address, address_source)
        VALUES (:dv, 'C', 'C', 'homicide', 'c-bp-test', 'XX', NULL, NULL)
        RETURNING case_id
    """),
        {"dv": dvid},
    ).scalar()

    db_session.commit()
    yield {"a": cid_a, "b": cid_b, "c": cid_c}

    # Cleanup
    db_session.execute(
        text("DELETE FROM cold_case.case_extractions WHERE case_id = ANY(:ids)"),
        {"ids": [cid_a, cid_b]},
    )
    db_session.execute(
        text("DELETE FROM cold_case.cases WHERE case_id = ANY(:ids)"),
        {"ids": [cid_a, cid_b, cid_c]},
    )
    db_session.execute(
        text("DELETE FROM etl.dataset_version WHERE dataset_version_id = :dv"), {"dv": dvid}
    )
    db_session.execute(text("DELETE FROM etl.source_system WHERE source_code='TEST_PROV_BACKFILL'"))
    db_session.commit()


def test_canonical_matching_tier2_tagged_tier2(db_engine: Engine, db_session: Session, seeded_cases: Any) -> None:
    run_backfill(db_engine)
    row = db_session.execute(
        text("SELECT address_source FROM cold_case.cases WHERE case_id=:c"),
        {"c": seeded_cases["a"]},
    ).one()
    assert row.address_source == "tier2"


def test_canonical_not_matching_tier2_tagged_source(db_engine: Engine, db_session: Session, seeded_cases: Any) -> None:
    run_backfill(db_engine)
    row = db_session.execute(
        text("SELECT address_source FROM cold_case.cases WHERE case_id=:c"),
        {"c": seeded_cases["b"]},
    ).one()
    assert row.address_source == "source"


def test_null_canonical_stays_null_source(db_engine: Engine, db_session: Session, seeded_cases: Any) -> None:
    run_backfill(db_engine)
    row = db_session.execute(
        text("SELECT address_source FROM cold_case.cases WHERE case_id=:c"),
        {"c": seeded_cases["c"]},
    ).one()
    assert row.address_source is None


def test_idempotent(db_engine: Engine, db_session: Session, seeded_cases: Any) -> None:
    run_backfill(db_engine)
    run_backfill(db_engine)  # second run should be a no-op
    row = db_session.execute(
        text("SELECT address_source FROM cold_case.cases WHERE case_id=:c"),
        {"c": seeded_cases["a"]},
    ).one()
    assert row.address_source == "tier2"

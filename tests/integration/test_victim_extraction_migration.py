"""Migration 0017 behavior tests: cold_case.victim_extraction table."""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

from tests.support.db_guard import resolve_test_database_url

_DATABASE_URL = resolve_test_database_url()


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(_DATABASE_URL)
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        try:
            yield s
        finally:
            s.rollback()
            s.execute(
                text(
                    "DELETE FROM cold_case.cases WHERE case_name LIKE 'TEST_VE_%'"
                )
            )
            s.execute(
                text(
                    "DELETE FROM etl.dataset_version"
                    " WHERE source_label LIKE 'Test VE Migration%'"
                    "   AND source_system_id = ("
                    "     SELECT source_system_id FROM etl.source_system"
                    "     WHERE source_code = 'TEST_VE'"
                    "   )"
                )
            )
            s.execute(
                text("DELETE FROM etl.source_system WHERE source_code = 'TEST_VE'")
            )
            s.commit()
    engine.dispose()


def _seed_dataset_version(session: Session, suffix: str = "") -> int:
    unique_hash = secrets.token_hex(8)
    sys_id = session.execute(
        text(
            "INSERT INTO etl.source_system (source_code, source_name) "
            "VALUES ('TEST_VE', 'Test VE Migration Source') "
            "ON CONFLICT (source_code) DO UPDATE SET source_name = EXCLUDED.source_name "
            "RETURNING source_system_id"
        )
    ).scalar_one()
    dataset_version_id = session.execute(
        text(
            "INSERT INTO etl.dataset_version"
            " (source_system_id, source_year, source_label, ingestion_status, source_hash)"
            " VALUES (:sys_id, 2026, :label, 'draft', :hash)"
            " RETURNING dataset_version_id"
        ),
        {"sys_id": sys_id, "label": f"Test VE Migration{suffix}", "hash": unique_hash},
    ).scalar_one()
    session.commit()
    return int(dataset_version_id)


def test_victim_extraction_table_exists(db_session: Session) -> None:
    """Table cold_case.victim_extraction must exist after migration 0017."""
    row = db_session.execute(
        text(
            "SELECT 1 FROM information_schema.tables"
            " WHERE table_schema = 'cold_case'"
            "   AND table_name   = 'victim_extraction'"
        )
    ).fetchone()
    assert row is not None, "cold_case.victim_extraction table does not exist"


def test_unique_constraint_fires(db_session: Session) -> None:
    """Inserting two victim_extraction rows with identical (case_id, model_id,
    prompt_hash, victim_ordinal) must raise IntegrityError on the second insert."""
    dvid = _seed_dataset_version(db_session, " unique_constraint")

    case_id = db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state)"
            " VALUES (:dvid, :sid, :slug, 'TEST_VE_unique', 'homicide', 'VA')"
            " RETURNING case_id"
        ),
        {"dvid": dvid, "sid": "test-ve-unique", "slug": "test-ve-unique"},
    ).scalar_one()
    db_session.commit()

    # First insert must succeed
    db_session.execute(
        text(
            "INSERT INTO cold_case.victim_extraction"
            " (case_id, victim_ordinal, model_id, prompt_hash, prompt_tier)"
            " VALUES (:cid, 1, 'test-model', 'deadbeef', 2)"
        ),
        {"cid": case_id},
    )
    db_session.commit()

    # Second insert with identical (case_id, model_id, prompt_hash, victim_ordinal)
    # must be rejected by the unique constraint.
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO cold_case.victim_extraction"
                    " (case_id, victim_ordinal, model_id, prompt_hash, prompt_tier)"
                    " VALUES (:cid, 1, 'test-model', 'deadbeef', 2)"
                ),
                {"cid": case_id},
            )


def test_fk_cascade_delete(db_session: Session) -> None:
    """Deleting a cold_case.cases row must cascade-delete its victim_extraction rows."""
    dvid = _seed_dataset_version(db_session, " cascade")

    # Insert a case
    case_id = db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state)"
            " VALUES (:dvid, :sid, :slug, 'TEST_VE_cascade', 'homicide', 'VA')"
            " RETURNING case_id"
        ),
        {"dvid": dvid, "sid": "test-ve-cascade", "slug": "test-ve-cascade"},
    ).scalar_one()
    db_session.commit()

    # Insert a victim_extraction row referencing that case
    db_session.execute(
        text(
            "INSERT INTO cold_case.victim_extraction"
            " (case_id, victim_ordinal, model_id, prompt_hash, prompt_tier)"
            " VALUES (:cid, 1, 'test-model', 'abc123', 2)"
        ),
        {"cid": case_id},
    )
    db_session.commit()

    # Confirm the row exists
    count_before = db_session.execute(
        text(
            "SELECT count(*) FROM cold_case.victim_extraction WHERE case_id = :cid"
        ),
        {"cid": case_id},
    ).scalar_one()
    assert count_before == 1, "victim_extraction row should exist before delete"

    # Delete the case — should cascade
    db_session.execute(
        text("DELETE FROM cold_case.cases WHERE case_id = :cid"),
        {"cid": case_id},
    )
    db_session.commit()

    # victim_extraction row must be gone
    count_after = db_session.execute(
        text(
            "SELECT count(*) FROM cold_case.victim_extraction WHERE case_id = :cid"
        ),
        {"cid": case_id},
    ).scalar_one()
    assert count_after == 0, (
        "victim_extraction row should have been cascade-deleted with its case"
    )

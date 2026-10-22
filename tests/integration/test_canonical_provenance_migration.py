"""Migration 0007: provenance columns on cold_case.cases + victim."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(os.environ["DATABASE_URL"])
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        try:
            yield s
        finally:
            s.rollback()
            s.execute(text("DELETE FROM cold_case.cases WHERE case_name LIKE 'TEST_PROV_%'"))
            s.execute(
                text(
                    "DELETE FROM etl.dataset_version"
                    " WHERE source_label LIKE 'Test Provenance%'"
                    "   AND source_system_id = ("
                    "     SELECT source_system_id FROM etl.source_system"
                    "     WHERE source_code = 'TEST_PROV'"
                    "   )"
                )
            )
            s.execute(text("DELETE FROM etl.source_system WHERE source_code = 'TEST_PROV'"))
            s.commit()
    engine.dispose()


def _seed_dataset_version(session: Session, suffix: str = "") -> int:
    import secrets

    unique_hash = secrets.token_hex(8)
    session.execute(
        text(
            "INSERT INTO etl.source_system (source_code, source_name)"
            " VALUES ('TEST_PROV', 'prov test') ON CONFLICT DO NOTHING"
        )
    )
    sys_id = session.execute(
        text("SELECT source_system_id FROM etl.source_system WHERE source_code = 'TEST_PROV'")
    ).scalar_one()
    dataset_version_id = session.execute(
        text(
            "INSERT INTO etl.dataset_version"
            " (source_system_id, source_year, source_label, ingestion_status, source_hash)"
            " VALUES (:sys_id, 2026, :label, 'draft', :hash)"
            " RETURNING dataset_version_id"
        ),
        {"sys_id": sys_id, "label": f"Test Provenance{suffix}", "hash": unique_hash},
    ).scalar_one()
    session.commit()
    return int(dataset_version_id)


def test_provenance_columns_exist(db_session: Session) -> None:
    """Verify the five provenance columns exist in their respective tables."""
    cases_cols = {
        r[0]
        for r in db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='cold_case' AND table_name='cases'"
            )
        )
    }
    assert "address_source" in cases_cols, "address_source column missing from cold_case.cases"
    assert (
        "incident_date_source" in cases_cols
    ), "incident_date_source column missing from cold_case.cases"

    victim_cols = {
        r[0]
        for r in db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='cold_case' AND table_name='victim'"
            )
        )
    }
    assert "age_source" in victim_cols, "age_source column missing from cold_case.victim"
    assert "gender_source" in victim_cols, "gender_source column missing from cold_case.victim"
    assert "race_source" in victim_cols, "race_source column missing from cold_case.victim"


def test_check_constraint_rejects_invalid_address_source(db_session: Session) -> None:
    """Verify CHECK constraint rejects values other than 'source', 'tier2', or NULL."""
    dvid = _seed_dataset_version(db_session, " check_addr")
    try:
        with db_session.begin_nested():
            db_session.execute(
                text("""
                INSERT INTO cold_case.cases (
                    dataset_version_id, source_case_id, case_name, case_type,
                    slug, state, address, address_source
                )
                VALUES (:dv, 'x-prov-addr', 'TEST_PROV_addr', 'homicide', 'x-prov-addr', 'XX',
                        '1 Main', 'invalid_value')
            """),
                {"dv": dvid},
            )
        raise AssertionError(
            "CHECK constraint should have rejected 'invalid_value' for address_source"
        )
    except IntegrityError:
        pass  # expected


def test_check_constraint_rejects_invalid_incident_date_source(db_session: Session) -> None:
    """Verify CHECK constraint rejects values other than 'source', 'tier2', or NULL."""
    dvid = _seed_dataset_version(db_session, " check_date")
    try:
        with db_session.begin_nested():
            db_session.execute(
                text("""
                INSERT INTO cold_case.cases (
                    dataset_version_id, source_case_id, case_name, case_type,
                    slug, state, incident_date_source
                )
                VALUES (:dv, 'x-prov-date', 'TEST_PROV_date', 'homicide', 'x-prov-date', 'XX',
                        'bad_value')
            """),
                {"dv": dvid},
            )
        raise AssertionError(
            "CHECK constraint should have rejected 'bad_value' for incident_date_source"
        )
    except IntegrityError:
        pass  # expected


def test_valid_provenance_values_accepted(db_session: Session) -> None:
    """Verify valid values ('source', 'tier2', NULL) are accepted."""
    dvid = _seed_dataset_version(db_session, " valid")
    case_row = db_session.execute(
        text("""
            INSERT INTO cold_case.cases (
                dataset_version_id, source_case_id, case_name, case_type,
                slug, state, address, address_source, incident_date_source
            )
            VALUES (:dv, 'x-prov-valid', 'TEST_PROV_valid', 'homicide', 'x-prov-valid', 'XX',
                    '1 Main', 'source', 'tier2')
            RETURNING case_id, address_source, incident_date_source
        """),
        {"dv": dvid},
    ).fetchone()
    db_session.commit()
    assert case_row is not None
    assert case_row.address_source == "source"
    assert case_row.incident_date_source == "tier2"


def test_victim_provenance_check_constraints(db_session: Session) -> None:
    """Verify victim provenance columns have CHECK constraints."""
    dvid = _seed_dataset_version(db_session, " victim_check")
    case_row = db_session.execute(
        text("""
            INSERT INTO cold_case.cases (
                dataset_version_id, source_case_id, case_name, case_type,
                slug, state
            )
            VALUES (:dv, 'x-prov-victim', 'TEST_PROV_victim', 'homicide', 'x-prov-victim', 'XX')
            RETURNING case_id
        """),
        {"dv": dvid},
    ).fetchone()
    assert case_row is not None

    # Valid values should work
    victim_row = db_session.execute(
        text("""
            INSERT INTO cold_case.victim (
                case_id, age_text, age_source, gender, gender_source, race, race_source
            )
            VALUES (:cid, '25', 'source', 'M', 'tier2', 'White', 'source')
            RETURNING victim_id, age_source, gender_source, race_source
        """),
        {"cid": case_row.case_id},
    ).fetchone()
    db_session.commit()
    assert victim_row is not None
    assert victim_row.age_source == "source"
    assert victim_row.gender_source == "tier2"
    assert victim_row.race_source == "source"

    # Invalid value should fail
    try:
        with db_session.begin_nested():
            db_session.execute(
                text("""
                INSERT INTO cold_case.victim (
                    case_id, age_text, age_source
                )
                VALUES (:cid, '30', 'invalid')
            """),
                {"cid": case_row.case_id},
            )
        raise AssertionError("CHECK constraint should have rejected 'invalid' for age_source")
    except IntegrityError:
        pass  # expected

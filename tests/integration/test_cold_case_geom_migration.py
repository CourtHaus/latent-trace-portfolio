"""GIS migration 0012 behavior tests: generated geom + age_num columns."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
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
            s.execute(text("DELETE FROM cold_case.cases WHERE case_name LIKE 'TEST_GEOM_%'"))
            s.execute(
                text(
                    "DELETE FROM etl.dataset_version"
                    " WHERE source_label LIKE 'Test Geom Migration%'"
                    "   AND source_system_id = ("
                    "     SELECT source_system_id FROM etl.source_system"
                    "     WHERE source_code = 'TEST_GEOM'"
                    "   )"
                )
            )
            s.execute(text("DELETE FROM etl.source_system WHERE source_code = 'TEST_GEOM'"))
            s.commit()
    engine.dispose()


def _seed_dataset_version(session: Session, suffix: str = "") -> int:
    import secrets

    unique_hash = secrets.token_hex(8)
    sys_id = session.execute(
        text(
            "INSERT INTO etl.source_system (source_code, source_name) "
            "VALUES ('TEST_GEOM', 'Test Geom Migration Source') "
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
        {"sys_id": sys_id, "label": f"Test Geom Migration{suffix}", "hash": unique_hash},
    ).scalar_one()
    session.commit()
    return int(dataset_version_id)


def test_geom_populates_from_lat_lon_on_insert(db_session: Session) -> None:
    dvid = _seed_dataset_version(db_session, " a")
    row = db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state,"
            "  latitude, longitude)"
            " VALUES (:dvid, :sid, :slug, 'TEST_GEOM_a', 'homicide', 'VA', 38.0, -78.5)"
            " RETURNING case_id, geom, ST_X(geom) AS lon, ST_Y(geom) AS lat"
        ),
        {"dvid": dvid, "sid": "test-geom-a", "slug": "test-geom-a"},
    ).fetchone()
    db_session.commit()
    assert row is not None
    assert row.geom is not None
    assert float(row.lon) == pytest.approx(-78.5, abs=1e-7)
    assert float(row.lat) == pytest.approx(38.0, abs=1e-7)


def test_geom_is_null_when_lat_or_lon_missing(db_session: Session) -> None:
    dvid = _seed_dataset_version(db_session, " b")
    row = db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state,"
            "  latitude, longitude)"
            " VALUES (:dvid, :sid, :slug, 'TEST_GEOM_b', 'homicide', 'VA', NULL, NULL)"
            " RETURNING geom"
        ),
        {"dvid": dvid, "sid": "test-geom-b", "slug": "test-geom-b"},
    ).fetchone()
    db_session.commit()
    assert row is not None
    assert row.geom is None


def test_generated_geom_invariant_for_inserted_rows(db_session: Session) -> None:
    dvid = _seed_dataset_version(db_session, " invariant")
    db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state,"
            "  latitude, longitude)"
            " VALUES"
            " (:dvid, 'test-geom-invariant-a', 'test-geom-invariant-a',"
            "  'TEST_GEOM_invariant_a', 'homicide', 'VA', 38.0, -78.5),"
            " (:dvid, 'test-geom-invariant-b', 'test-geom-invariant-b',"
            "  'TEST_GEOM_invariant_b', 'homicide', 'VA', NULL, NULL)"
        ),
        {"dvid": dvid},
    )
    db_session.commit()

    counts = db_session.execute(
        text(
            "SELECT"
            "  count(*) FILTER (WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND geom IS NULL) AS missing_geom,"
            "  count(*) FILTER (WHERE (latitude IS NULL OR longitude IS NULL) AND geom IS NOT NULL) AS spurious_geom,"
            "  count(*) FILTER (WHERE geom IS NOT NULL) AS with_geom"
            " FROM cold_case.cases"
            " WHERE dataset_version_id = :dvid"
        ),
        {"dvid": dvid},
    ).fetchone()
    assert counts is not None
    assert counts.missing_geom == 0, "rows with lat+lon should all have geom"
    assert counts.spurious_geom == 0, "rows without lat/lon must not have geom"
    assert counts.with_geom == 1


def test_age_num_parses_pure_integer(db_session: Session) -> None:
    dvid = _seed_dataset_version(db_session, " age")
    case_row = db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state)"
            " VALUES (:dvid, :sid, :slug, 'TEST_GEOM_age', 'homicide', 'VA')"
            " RETURNING case_id"
        ),
        {"dvid": dvid, "sid": "test-geom-age", "slug": "test-geom-age"},
    ).fetchone()
    assert case_row is not None
    victim_row = db_session.execute(
        text(
            "INSERT INTO cold_case.victim (case_id, age_text)"
            " VALUES (:cid, '42') RETURNING age_num"
        ),
        {"cid": case_row.case_id},
    ).fetchone()
    db_session.commit()
    assert victim_row is not None
    assert victim_row.age_num == 42


def test_age_num_is_null_for_non_numeric_text(db_session: Session) -> None:
    dvid = _seed_dataset_version(db_session, " age_unk")
    case_row = db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state)"
            " VALUES (:dvid, :sid, :slug, 'TEST_GEOM_age_unk', 'homicide', 'VA')"
            " RETURNING case_id"
        ),
        {"dvid": dvid, "sid": "test-geom-age-unk", "slug": "test-geom-age-unk"},
    ).fetchone()
    assert case_row is not None
    for raw in ["Unknown", "", "20-25", "99999999999"]:
        row = db_session.execute(
            text(
                "INSERT INTO cold_case.victim (case_id, age_text)"
                " VALUES (:cid, :raw) RETURNING age_num"
            ),
            {"cid": case_row.case_id, "raw": raw},
        ).fetchone()
        assert row is not None
        assert row.age_num is None, f"age_text={raw!r} should produce NULL age_num"
    db_session.commit()


def test_age_num_null_for_null_text(db_session: Session) -> None:
    dvid = _seed_dataset_version(db_session, " age_null")
    case_row = db_session.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state)"
            " VALUES (:dvid, :sid, :slug, 'TEST_GEOM_age_null', 'homicide', 'VA')"
            " RETURNING case_id"
        ),
        {"dvid": dvid, "sid": "test-geom-age-null", "slug": "test-geom-age-null"},
    ).fetchone()
    assert case_row is not None
    row = db_session.execute(
        text(
            "INSERT INTO cold_case.victim (case_id, age_text)"
            " VALUES (:cid, NULL) RETURNING age_num"
        ),
        {"cid": case_row.case_id},
    ).fetchone()
    db_session.commit()
    assert row is not None
    assert row.age_num is None

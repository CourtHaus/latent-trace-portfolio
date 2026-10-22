"""Geocoding worker — claim race + crash recovery + execute_job paths."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from casesignal.geocoding.service import GeocodeResult, GeocodingService
from casesignal.worker import geocoding_loop

# ---------- in-memory unit tests (no DB) ----------


class _FakeSession:
    """Minimal session fake recording SQL + params; for execute_job tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.committed_count = 0

    def execute(self, statement: Any, params: Any = None) -> Any:
        self.calls.append((str(statement), dict(params or {})))

        class _Result:
            def fetchone(self_inner: Any) -> Any:
                return None

        return _Result()

    def commit(self) -> None:
        self.committed_count += 1


class _StubService:
    def __init__(self, result: GeocodeResult) -> None:
        self.result = result
        self.calls = 0

    def geocode_for_job(self, job_input: Any) -> Any:
        self.calls += 1
        return self.result


def test_execute_job_street_precision_updates_case_with_coords() -> None:
    session = _FakeSession()
    service = _StubService(
        GeocodeResult(latitude=39.3, longitude=-76.5, precision="street", notes="ok")
    )

    geocoding_loop.execute_job(
        {
            "geocoding_job_id": 7,
            "case_id": 100,
            "address_text": "6000 Barstow Rd",
            "state_code": "MD",
            "zip_code": "21206",
            "county_fips": "24005",
        },
        session=cast(Session, session),
        service=cast(GeocodingService, service),
    )

    # Find the cases UPDATE
    cases_updates = [(sql, p) for (sql, p) in session.calls if "cold_case.cases" in sql]
    assert len(cases_updates) == 1
    sql, params = cases_updates[0]
    assert "latitude" in sql and "longitude" in sql and "geocode_precision" in sql
    assert params["lat"] == 39.3
    assert params["lon"] == -76.5
    assert params["precision"] == "street"
    assert params["cid"] == 100

    # Find the job-status UPDATE
    job_updates = [(sql, p) for (sql, p) in session.calls if "cold_case.geocoding_job" in sql]
    assert len(job_updates) == 1
    sql, params = job_updates[0]
    assert "succeeded" in sql
    assert params["jid"] == 7

    assert session.committed_count == 1


def test_execute_job_failed_precision_does_not_touch_coords() -> None:
    """precision='failed' means lat/lon stays NULL on the case row."""
    session = _FakeSession()
    service = _StubService(
        GeocodeResult(latitude=None, longitude=None, precision="failed", notes="no hit")
    )

    geocoding_loop.execute_job(
        {
            "geocoding_job_id": 9,
            "case_id": 200,
            "address_text": "totally unknown",
            "state_code": "ZZ",
            "zip_code": None,
            "county_fips": None,
        },
        session=cast(Session, session),
        service=cast(GeocodingService, service),
    )

    cases_updates = [(sql, p) for (sql, p) in session.calls if "cold_case.cases" in sql]
    assert len(cases_updates) == 1
    sql, params = cases_updates[0]
    # Failed-path UPDATE only sets geocode_precision, not lat/lon
    assert "latitude" not in sql
    assert params["precision"] == "failed"
    assert params["cid"] == 200


def test_execute_job_exception_marks_failed_and_truncates_error() -> None:
    session = _FakeSession()

    class _ExplodingService:
        def geocode_for_job(self, job_input: Any) -> None:
            raise RuntimeError("x" * 5000)

    geocoding_loop.execute_job(
        {
            "geocoding_job_id": 11,
            "case_id": 300,
            "address_text": "addr",
            "state_code": "MD",
            "zip_code": None,
            "county_fips": None,
        },
        session=cast(Session, session),
        service=cast(GeocodingService, _ExplodingService()),
    )

    failed = [(sql, p) for (sql, p) in session.calls if "status='failed'" in sql]
    assert len(failed) == 1
    _, params = failed[0]
    assert params["jid"] == 11
    assert len(params["e"]) == 1000  # truncated


# ---------- DB-gated integration tests ----------


def _db_url() -> str:
    return os.environ["DATABASE_URL"]


pytestmark_db = pytest.mark.skipif(
    "DATABASE_URL" not in os.environ,
    reason="DATABASE_URL not set; geocoding worker DB tests require live Postgres.",
)


def _seed_test_case(conn: Any) -> int:
    """Insert a synthetic case + dataset_version into the DB and return case_id."""
    sys_id = conn.execute(
        text(
            "INSERT INTO etl.source_system (source_code, source_name) "
            "VALUES ('TEST_GEO', 'Test Geocoding')"
            " ON CONFLICT (source_code) DO UPDATE SET source_code='TEST_GEO'"
            " RETURNING source_system_id"
        )
    ).scalar_one()
    dv_id = conn.execute(
        text(
            "INSERT INTO etl.dataset_version"
            " (source_system_id, source_year, source_label, source_hash, ingestion_status)"
            " VALUES (:sid, 2026, 'TEST_GEO_DV', md5(random()::text), 'draft')"
            " RETURNING dataset_version_id"
        ),
        {"sid": sys_id},
    ).scalar_one()
    case_id = conn.execute(
        text(
            "INSERT INTO cold_case.cases"
            " (dataset_version_id, source_case_id, slug, case_name, case_type, state)"
            " VALUES (:dv, 'test-geo-' || md5(random()::text), 'test-geo-' || md5(random()::text), 'Geo Test', 'homicide', 'MD')"
            " RETURNING case_id"
        ),
        {"dv": dv_id},
    ).scalar_one()
    return int(case_id)


@pytestmark_db
def test_claim_next_job_skip_locked_under_two_workers() -> None:
    """Two simulated workers; only one wins each queued job."""
    engine = create_engine(_db_url())
    with engine.begin() as conn:
        case_id = _seed_test_case(conn)
        job_id = conn.execute(
            text(
                "INSERT INTO cold_case.geocoding_job"
                " (case_id, address_text, state_code)"
                " VALUES (:cid, '100 Main St', 'MD')"
                " RETURNING geocoding_job_id"
            ),
            {"cid": case_id},
        ).scalar_one()

    conn_a = engine.connect()
    conn_b = engine.connect()
    try:
        tx_a = conn_a.begin()
        claim_a = conn_a.execute(geocoding_loop._CLAIM_SQL, {"worker_id": "worker-a"}).fetchone()

        tx_b = conn_b.begin()
        claim_b = conn_b.execute(geocoding_loop._CLAIM_SQL, {"worker_id": "worker-b"}).fetchone()

        tx_a.commit()
        tx_b.commit()

        winners = [c for c in (claim_a, claim_b) if c is not None]
        assert len(winners) == 1
        assert winners[0].geocoding_job_id == job_id
    finally:
        conn_a.close()
        conn_b.close()
        with engine.begin() as cleanup:
            cleanup.execute(
                text("DELETE FROM cold_case.geocoding_job" " WHERE geocoding_job_id = :j"),
                {"j": job_id},
            )
            cleanup.execute(
                text("DELETE FROM cold_case.cases WHERE case_id = :c"),
                {"c": case_id},
            )
        engine.dispose()


@pytestmark_db
def test_crash_recovery_marks_stuck_running_jobs_failed() -> None:
    engine = create_engine(_db_url())
    try:
        with engine.begin() as conn:
            case_id = _seed_test_case(conn)
            old = conn.execute(
                text(
                    "INSERT INTO cold_case.geocoding_job"
                    " (case_id, address_text, status, worker_started_at, worker_id)"
                    " VALUES (:cid, '100 Main', 'running',"
                    "         NOW() - INTERVAL '3 hours', 'old')"
                    " RETURNING geocoding_job_id"
                ),
                {"cid": case_id},
            ).scalar_one()
            fresh = conn.execute(
                text(
                    "INSERT INTO cold_case.geocoding_job"
                    " (case_id, address_text, status, worker_started_at, worker_id)"
                    " VALUES (:cid, '200 Main', 'running',"
                    "         NOW() - INTERVAL '1 hour', 'fresh')"
                    " RETURNING geocoding_job_id"
                ),
                {"cid": case_id},
            ).scalar_one()

        with engine.begin() as conn:
            conn.execute(geocoding_loop._RECOVERY_SQL)

        with engine.connect() as conn:
            old_row = conn.execute(
                text(
                    "SELECT status, error_detail FROM cold_case.geocoding_job"
                    " WHERE geocoding_job_id=:j"
                ),
                {"j": old},
            ).fetchone()
            fresh_row = conn.execute(
                text("SELECT status FROM cold_case.geocoding_job" " WHERE geocoding_job_id=:j"),
                {"j": fresh},
            ).fetchone()

        assert old_row is not None
        assert fresh_row is not None
        assert old_row.status == "failed"
        assert old_row.error_detail == "worker crash recovery"
        assert fresh_row.status == "running"
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM cold_case.geocoding_job" " WHERE worker_id IN ('old', 'fresh')")
            )
            conn.execute(text("DELETE FROM cold_case.cases" " WHERE case_name='Geo Test'"))
        engine.dispose()

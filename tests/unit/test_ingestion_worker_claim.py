"""SEC-021: ingestion worker unit tests — claim race, crash recovery, exception path."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from casesignal.api.services.ingestion import IngestionAdminService
from casesignal.worker import ingestion_loop


class _FakeSession:
    """In-memory fake that records executed SQL + params; for execute_job exception path."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.committed = False

    def execute(self, statement: Any, params: Any = None) -> Any:
        self.calls.append((str(statement), dict(params or {})))

        class _Result:
            def fetchone(self_inner: Any) -> Any:
                return None

        return _Result()

    def commit(self) -> None:
        self.committed = True


def test_execute_job_marks_failed_and_truncates_error_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """When run_source_definition raises, the job row is updated to failed with
    the exception message truncated to 1000 chars."""

    class _FakeService:
        def build_source_definition(self, request: Any) -> Any:
            return "SOURCE_DEFINITION_SENTINEL"

    huge = "x" * 5000

    def _exploding_pipeline(source_definition: Any) -> None:
        assert source_definition == "SOURCE_DEFINITION_SENTINEL"
        raise RuntimeError(huge)

    monkeypatch.setattr(ingestion_loop, "run_source_definition", _exploding_pipeline)

    session = _FakeSession()
    ingestion_loop.execute_job(
        {
            "ingestion_job_id": 7,
            "source_definition_json": {
                "source_key": "x",
                "source_family": "cold_case",
                "adapter_name": "cold_case_va",
            },
        },
        session=cast(Session, session),
        service=cast(IngestionAdminService, _FakeService()),
    )

    failing_calls = [c for c in session.calls if "status='failed'" in c[0]]
    assert len(failing_calls) == 1
    _, params = failing_calls[0]
    assert params["jid"] == 7
    assert len(params["e"]) == 1000
    assert session.committed is True


def _db_url() -> str:
    return os.environ["DATABASE_URL"]


pytestmark_db = pytest.mark.skipif(
    "DATABASE_URL" not in os.environ,
    reason="DATABASE_URL not set; ingestion worker DB tests require live Postgres.",
)


@pytestmark_db
def test_claim_next_job_is_race_safe_under_skip_locked() -> None:
    """Two sessions attempt to claim a single queued job; exactly one wins."""
    engine = create_engine(_db_url())
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO etl.ingestion_job (status, source_definition_json)"
                " VALUES ('queued', '{}'::jsonb) RETURNING ingestion_job_id"
            )
        ).fetchone()
        assert row is not None
        job_id = row.ingestion_job_id

    conn_a = engine.connect()
    conn_b = engine.connect()
    try:
        tx_a = conn_a.begin()
        claim_a = conn_a.execute(ingestion_loop._CLAIM_SQL, {"worker_id": "a"}).fetchone()

        tx_b = conn_b.begin()
        claim_b = conn_b.execute(ingestion_loop._CLAIM_SQL, {"worker_id": "b"}).fetchone()

        tx_a.commit()
        tx_b.commit()

        winners = [c for c in (claim_a, claim_b) if c is not None]
        assert len(winners) == 1
        assert winners[0].ingestion_job_id == job_id
    finally:
        conn_a.close()
        conn_b.close()
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM etl.ingestion_job WHERE ingestion_job_id = :j"),
                {"j": job_id},
            )
        engine.dispose()


@pytestmark_db
def test_crash_recovery_resets_stuck_running_rows_older_than_two_hours() -> None:
    engine = create_engine(_db_url())
    try:
        with engine.begin() as conn:
            old = conn.execute(
                text(
                    "INSERT INTO etl.ingestion_job"
                    " (status, source_definition_json, worker_started_at, worker_id)"
                    " VALUES ('running', '{}'::jsonb, NOW() - INTERVAL '3 hours', 'old')"
                    " RETURNING ingestion_job_id"
                )
            ).fetchone()
            assert old is not None
            fresh = conn.execute(
                text(
                    "INSERT INTO etl.ingestion_job"
                    " (status, source_definition_json, worker_started_at, worker_id)"
                    " VALUES ('running', '{}'::jsonb, NOW() - INTERVAL '1 hour', 'fresh')"
                    " RETURNING ingestion_job_id"
                )
            ).fetchone()
            assert fresh is not None

        with engine.begin() as conn:
            conn.execute(ingestion_loop._RECOVERY_SQL)

        with engine.connect() as conn:
            old_row = conn.execute(
                text(
                    "SELECT status, error_detail FROM etl.ingestion_job WHERE ingestion_job_id = :j"
                ),
                {"j": old.ingestion_job_id},
            ).fetchone()
            assert old_row is not None
            fresh_row = conn.execute(
                text("SELECT status FROM etl.ingestion_job WHERE ingestion_job_id = :j"),
                {"j": fresh.ingestion_job_id},
            ).fetchone()
            assert fresh_row is not None

        assert old_row.status == "failed"
        assert old_row.error_detail == "worker crash recovery"
        assert fresh_row.status == "running"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM etl.ingestion_job WHERE worker_id IN ('old','fresh')"))
        engine.dispose()

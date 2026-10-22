from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from casesignal.api.app import create_app
from casesignal.api.dependencies.db import get_db_session
from casesignal.api.dependencies.operator_auth import SupabaseAdminUser, require_operator_admin
from casesignal.api.schemas.operator import (
    OperatorDatasetSnapshot,
    OperatorPipelineSnapshot,
    OperatorSnapshotResponse,
    OperatorStatusCounts,
    OperatorSystemSnapshot,
)


def _snapshot() -> OperatorSnapshotResponse:
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    empty_counts = OperatorStatusCounts(queued=0, running=0, succeeded=0, failed=0, partial=0, skipped=0)
    return OperatorSnapshotResponse(
        system=OperatorSystemSnapshot(
            health="healthy",
            generated_at=now,
            database_ok=True,
            environment="test",
        ),
        dataset=OperatorDatasetSnapshot(
            version="v2026.05",
            published_dataset_versions=1,
            total_cases=2,
            state_count=1,
            source_count=1,
            geocoded_cases=2,
            geocoded_percent=100.0,
            last_ingested_at=now,
            last_published_at=now,
        ),
        pipeline=OperatorPipelineSnapshot(
            ingestion=empty_counts,
            extraction=empty_counts,
            geocoding=empty_counts,
            stale_running_count=0,
            old_queued_count=0,
        ),
        warnings=[],
        latest_failures=[],
        sources=[],
    )


class FakeSession:
    pass


def test_operator_snapshot_requires_auth() -> None:
    app = create_app()

    def fake_session() -> Iterator[FakeSession]:
        yield FakeSession()

    app.dependency_overrides[get_db_session] = fake_session
    with TestClient(app) as client:
        response = client.get("/api/v1/operator/snapshot")
    assert response.status_code == 401


def test_operator_snapshot_returns_payload(monkeypatch: MonkeyPatch) -> None:
    app = create_app()
    fake_db_session = FakeSession()
    captured: dict[str, FakeSession] = {}

    def fake_session() -> Iterator[FakeSession]:
        yield fake_db_session

    def fake_get_operator_snapshot(session: FakeSession) -> OperatorSnapshotResponse:
        captured["session"] = session
        return _snapshot()

    app.dependency_overrides[get_db_session] = fake_session
    app.dependency_overrides[require_operator_admin] = lambda: SupabaseAdminUser(
        supabase_user_id="11111111-1111-1111-1111-111111111111",
        email="admin@example.com",
    )
    monkeypatch.setattr(
        "casesignal.api.routes.operator.get_operator_snapshot",
        fake_get_operator_snapshot,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/operator/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["system"]["health"] == "healthy"
    assert body["dataset"]["total_cases"] == 2
    assert captured["session"] is fake_db_session

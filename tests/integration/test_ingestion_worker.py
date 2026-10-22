"""SEC-021: end-to-end — POST /admin/ingestion/runs → worker claim → completion → GET /jobs."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.api.app import create_app
from casesignal.api.dependencies.auth import AuthenticatedKey, require_api_key
from casesignal.api.routes.admin.ingestion import get_ingestion_service
from casesignal.api.services.ingestion import IngestionAdminService
from casesignal.worker import ingestion_loop

pytestmark = pytest.mark.integration


class _StubService(IngestionAdminService):
    """Bypasses real catalog/upload-root validation. Still uses the inherited
    trigger_run / get_job_status — which talk to the real DB."""

    def build_source_definition(self, request: Any) -> Any:
        return "SENTINEL_SOURCE_DEFINITION"


@pytest.fixture
def admin_client() -> Iterator[TestClient]:
    app = create_app()

    def override_key(request: Request) -> AuthenticatedKey:
        request.state.api_key_id = 999
        return AuthenticatedKey(key_id=999, role="admin")

    app.dependency_overrides[require_api_key] = override_key
    app.dependency_overrides[get_ingestion_service] = lambda: _StubService()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(os.environ["DATABASE_URL"])
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        try:
            yield s
        finally:
            s.rollback()
            s.execute(
                text("DELETE FROM etl.ingestion_job WHERE worker_id = :w"),
                {"w": ingestion_loop.WORKER_ID},
            )
            s.commit()
    engine.dispose()


def test_post_run_enqueues_and_worker_drives_job_to_succeeded(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeRunResult:
        run_status = "succeeded"
        ingestion_run_id = None  # worker UPDATE tolerates NULL via the nullable FK

    monkeypatch.setattr(
        ingestion_loop, "run_source_definition", lambda source_def: _FakeRunResult()
    )

    payload = {
        "source_key": "test_cold_case_va_dummy",
        "source_family": "cold_case",
        "adapter_name": "cold_case_va",
        "source_code": "VSPCCD",
        "source_name": "Test cold case source",
        "source_year": 2026,
        "source_state": "VA",
        "input_path": "/tmp/nonexistent.csv",
        "input_type": "file",
        "description": "Test ingestion worker request body — request only, never executed.",
        "metadata": {},
    }
    resp = admin_client.post("/api/v1/admin/ingestion/runs", json=payload)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    job_id = body["ingestion_job_id"]

    claim = ingestion_loop.claim_next_job(db_session)
    assert claim is not None
    assert claim["ingestion_job_id"] == job_id

    ingestion_loop.execute_job(claim, db_session, _StubService())

    resp = admin_client.get(f"/api/v1/admin/ingestion/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["worker_started_at"] is not None
    assert body["worker_completed_at"] is not None

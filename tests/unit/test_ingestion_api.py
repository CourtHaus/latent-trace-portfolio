from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from casesignal.api.dependencies.auth import AuthenticatedKey
from casesignal.api.services.ingestion import IngestionAdminService

NOW = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)


class FakeIngestionService:
    def __init__(self) -> None:
        self.upload_content: bytes | None = None
        self.run_request: Any = None
        self.run_session: Any = None

    def stage_upload(
        self,
        *,
        content: bytes,
        source_key: str,
        source_code: str,
        source_name: str,
        source_year: int,
        source_state: str | None,
        input_type: str,
    ) -> Any:
        self.upload_content = content
        return {
            "source_key": source_key,
            "source_code": source_code,
            "source_name": source_name,
            "source_year": source_year,
            "source_state": source_state,
            "input_type": input_type,
            "staged_path": "data/raw/uploads/nibrs_va_2025/nibrs_va_2025.zip",
            "size_bytes": len(content),
        }

    def trigger_run(self, request: Any, session: Any) -> Any:
        self.run_request = request
        self.run_session = session
        return {
            "source_key": request.source_key,
            "ingestion_job_id": 77,
            "status": "queued",
        }

    def get_run_status(self, session: Any, ingestion_run_id: int) -> Any:
        return {
            "ingestion_run_id": ingestion_run_id,
            "dataset_version_id": 31,
            "run_status": "succeeded",
            "started_at": NOW,
            "completed_at": NOW,
            "rows_read": 100,
            "rows_loaded": 100,
            "rows_rejected": 0,
            "notes": "done",
            "stages": [
                {
                    "ingestion_run_stage_id": 7,
                    "stage_name": "publish",
                    "stage_status": "succeeded",
                    "started_at": NOW,
                    "completed_at": NOW,
                    "rows_read": 100,
                    "rows_loaded": 100,
                    "notes": None,
                }
            ],
        }

    def get_job_status(self, session: Any, ingestion_job_id: int) -> Any:
        return {
            "ingestion_job_id": ingestion_job_id,
            "status": "succeeded",
            "created_at": NOW,
            "worker_id": "host-1-99",
            "worker_started_at": NOW,
            "worker_completed_at": NOW,
            "error_detail": None,
            "ingestion_run_id": 44,
        }

    def publish_dataset_version(self, session: Any, dataset_version_id: int) -> Any:
        return {
            "dataset_version_id": dataset_version_id,
            "ingestion_status": "published",
            "published_at": NOW,
        }

    def unpublish_dataset_version(self, session: Any, dataset_version_id: int) -> Any:
        return {
            "dataset_version_id": dataset_version_id,
            "ingestion_status": "archived",
            "published_at": None,
        }


def _fake_session() -> Session:
    return cast(Session, object())


def _fake_ingestion_service(service: FakeIngestionService) -> IngestionAdminService:
    return cast(IngestionAdminService, service)


def test_upload_endpoint_stages_base64_request_body() -> None:
    from casesignal.api.routes.admin.ingestion import IngestionUploadRequest, upload_dataset

    service = FakeIngestionService()

    response = upload_dataset(
        IngestionUploadRequest(
            source_key="nibrs_va_2025",
            source_code="FBI_NIBRS",
            source_name="Virginia NIBRS",
            source_year=2025,
            source_state="VA",
            content_base64=base64.b64encode(b"zip-bytes").decode("ascii"),
        ),
        service=_fake_ingestion_service(service),
        _auth=AuthenticatedKey(key_id=1, role="admin"),
    )

    body = response.model_dump(mode="json")
    assert body["source_key"] == "nibrs_va_2025"
    assert body["staged_path"].endswith("nibrs_va_2025.zip")
    assert body["size_bytes"] == 9
    assert service.upload_content == b"zip-bytes"


def test_run_endpoint_enqueues_ingestion_job_and_returns_job_id() -> None:
    from casesignal.api.routes.admin.ingestion import IngestionRunRequest, trigger_ingestion_run

    service = FakeIngestionService()

    response = trigger_ingestion_run(
        IngestionRunRequest(
            source_key="nibrs_va_2025",
            source_family="cold_case",
            adapter_name="cold_case_va",
            source_code="FBI_NIBRS",
            source_name="Virginia NIBRS",
            source_year=2025,
            source_state="VA",
            input_path="data/raw/uploads/nibrs_va_2025/nibrs_va_2025.zip",
        ),
        session=_fake_session(),
        service=_fake_ingestion_service(service),
        _auth=AuthenticatedKey(key_id=1, role="admin"),
    )

    body = response.model_dump(mode="json")
    assert body == {
        "source_key": "nibrs_va_2025",
        "ingestion_job_id": 77,
        "status": "queued",
    }
    assert service.run_request.source_key == "nibrs_va_2025"


def test_status_endpoint_returns_ingestion_run_and_stage_status() -> None:
    from casesignal.api.routes.admin.ingestion import get_ingestion_run_status

    service = FakeIngestionService()

    response = get_ingestion_run_status(
        44,
        session=_fake_session(),
        service=_fake_ingestion_service(service),
        _auth=AuthenticatedKey(key_id=1, role="admin"),
    )

    body = response.model_dump(mode="json")
    assert body["ingestion_run_id"] == 44
    assert body["run_status"] == "succeeded"
    assert body["stages"][0]["stage_name"] == "publish"


def test_publish_and_unpublish_endpoints_return_lifecycle_state() -> None:
    from casesignal.api.routes.admin.ingestion import (
        publish_dataset_version,
        unpublish_dataset_version,
    )

    service = FakeIngestionService()

    publish_response = publish_dataset_version(
        31,
        session=_fake_session(),
        service=_fake_ingestion_service(service),
        _auth=AuthenticatedKey(key_id=1, role="admin"),
    )
    unpublish_response = unpublish_dataset_version(
        31,
        session=_fake_session(),
        service=_fake_ingestion_service(service),
        _auth=AuthenticatedKey(key_id=1, role="admin"),
    )

    assert publish_response.ingestion_status == "published"
    assert unpublish_response.model_dump(mode="json") == {
        "dataset_version_id": 31,
        "ingestion_status": "archived",
        "published_at": None,
    }


def test_service_stages_upload_under_source_key_directory(tmp_path: Path) -> None:
    from casesignal.api.services.ingestion import IngestionAdminService

    service = IngestionAdminService(upload_root=tmp_path)

    response = service.stage_upload(
        content=b"zip-bytes",
        source_key="nibrs_va_2025",
        source_code="FBI_NIBRS",
        source_name="Virginia NIBRS",
        source_year=2025,
        source_state="va",
        input_type="zip",
    )

    staged_path = Path(response["staged_path"])
    assert staged_path == tmp_path / "nibrs_va_2025" / "nibrs_va_2025.zip"
    assert staged_path.read_bytes() == b"zip-bytes"
    assert response["source_state"] == "VA"
    assert response["size_bytes"] == 9


class FakeResult:
    def __init__(self, row: Any = None, rows: Any = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> Any:
        return self._rows


class FakeRow:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeLifecycleSession:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.committed = False

    def execute(self, statement: Any, params: Any = None) -> Any:
        sql = str(statement)
        self.statements.append(sql)
        if "UPDATE etl.dataset_version" in sql:
            return FakeResult(
                FakeRow(
                    dataset_version_id=params["dataset_version_id"],
                    ingestion_status="published" if "published_at = NOW()" in sql else "archived",
                    published_at=NOW if "published_at = NOW()" in sql else None,
                )
            )
        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self) -> None:
        self.committed = True


class FakeStatusSession:
    def execute(self, statement: Any, params: Any = None) -> Any:
        sql = str(statement)
        if "FROM etl.ingestion_run_stage" in sql:
            return FakeResult(
                rows=[
                    FakeRow(
                        ingestion_run_stage_id=7,
                        stage_name="publish",
                        stage_status="succeeded",
                        started_at=NOW,
                        completed_at=NOW,
                        rows_read=100,
                        rows_loaded=100,
                        notes=None,
                    )
                ]
            )
        if "FROM etl.ingestion_run" in sql:
            return FakeResult(
                FakeRow(
                    ingestion_run_id=params["ingestion_run_id"],
                    dataset_version_id=31,
                    run_status="succeeded",
                    started_at=NOW,
                    completed_at=NOW,
                    rows_read=100,
                    rows_loaded=100,
                    rows_rejected=0,
                    notes="done",
                )
            )
        raise AssertionError(f"Unexpected SQL: {sql}")


def test_service_get_run_status_includes_stage_rows() -> None:
    from casesignal.api.services.ingestion import IngestionAdminService

    service = IngestionAdminService()

    result = service.get_run_status(cast(Session, FakeStatusSession()), 44)

    assert result["ingestion_run_id"] == 44
    assert result["dataset_version_id"] == 31
    assert result["stages"][0]["stage_name"] == "publish"


def test_service_build_source_definition_rejects_path_traversal(
    tmp_path: Path, caplog: Any
) -> None:
    import logging

    import pytest

    from casesignal.api.services.ingestion import IngestionAdminService

    service = IngestionAdminService(upload_root=tmp_path)

    class FakeRunRequest:
        source_key = "nibrs_va_2025"
        source_family = None
        adapter_name = None
        source_code = "FBI_NIBRS"
        source_name = "Virginia NIBRS"
        source_year = 2025
        source_state = None
        input_path = str(tmp_path / ".." / "outside" / "file.zip")
        input_type = "zip"
        required_files = None
        optional_files = None
        description = None
        metadata = None

    # SEC-B06: client-facing message is generic (no upload-root path leak)...
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match="not an allowed location"):
            service.build_source_definition(FakeRunRequest())
    # ...but the specifics (resolved path + root) are logged server-side.
    assert any("outside upload root" in r.message for r in caplog.records)


def test_service_publish_and_unpublish_commit_status_changes() -> None:
    from casesignal.api.services.ingestion import IngestionAdminService

    service = IngestionAdminService()
    session = FakeLifecycleSession()

    published = service.publish_dataset_version(cast(Session, session), 31)
    unpublished = service.unpublish_dataset_version(cast(Session, session), 31)

    assert published["ingestion_status"] == "published"
    assert unpublished["ingestion_status"] == "archived"
    assert session.committed is True


def test_job_status_endpoint_returns_queue_state_and_run_id_when_present() -> None:
    from casesignal.api.routes.admin.ingestion import get_ingestion_job_status

    service = FakeIngestionService()

    response = get_ingestion_job_status(
        77,
        session=_fake_session(),
        service=_fake_ingestion_service(service),
        _auth=AuthenticatedKey(key_id=1, role="admin"),
    )

    body = response.model_dump(mode="json")
    assert body["ingestion_job_id"] == 77
    assert body["status"] == "succeeded"
    assert body["ingestion_run_id"] == 44
    assert body["error_detail"] is None

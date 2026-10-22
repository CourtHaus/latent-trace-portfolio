from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from casesignal.api.dependencies.auth import AuthenticatedKey, require_admin
from casesignal.api.dependencies.db import get_db_session
from casesignal.api.services.ingestion import IngestionAdminService

router = APIRouter(prefix="/admin/ingestion", tags=["admin"])


class IngestionUploadResponse(BaseModel):
    source_key: str
    source_code: str
    source_name: str
    source_year: int
    source_state: str | None
    input_type: str
    staged_path: str
    size_bytes: int

    model_config = ConfigDict(extra="forbid")


class IngestionUploadRequest(BaseModel):
    source_key: str = Field(..., max_length=50)
    source_code: str = Field(..., max_length=50)
    source_name: str
    source_year: int = Field(..., ge=1900, le=2100)
    source_state: str | None = None
    input_type: Literal["zip"] = "zip"
    # 100 MB raw * base64 overhead (~1.37x) ≈ 137 MB max base64 string.
    # Capped intentionally low because the API decodes the whole payload in
    # RAM. Raise if a real source needs more; until then this bounds the
    # compromised-admin DoS surface.
    content_base64: str = Field(..., max_length=137_000_000)

    model_config = ConfigDict(extra="forbid")


class IngestionRunRequest(BaseModel):
    source_key: str
    input_path: str | None = None
    source_family: str
    adapter_name: str
    source_code: str | None = None
    source_name: str | None = None
    input_type: Literal["zip", "directory", "file"] = "zip"
    source_year: int | None = Field(default=None, ge=1900, le=2100)
    source_state: str | None = None
    required_files: list[str] = Field(default_factory=list)
    optional_files: list[str] = Field(default_factory=list)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class IngestionRunResponse(BaseModel):
    source_key: str
    ingestion_job_id: int
    status: Literal["queued"] = "queued"

    model_config = ConfigDict(extra="forbid")


class IngestionRunStageResponse(BaseModel):
    ingestion_run_stage_id: int
    stage_name: str
    stage_status: str
    started_at: datetime
    completed_at: datetime | None
    rows_read: int | None
    rows_loaded: int | None
    notes: str | None

    model_config = ConfigDict(extra="forbid")


class IngestionRunStatusResponse(BaseModel):
    ingestion_run_id: int
    dataset_version_id: int
    run_status: str
    started_at: datetime
    completed_at: datetime | None
    rows_read: int | None
    rows_loaded: int | None
    rows_rejected: int | None
    notes: str | None
    stages: list[IngestionRunStageResponse]

    model_config = ConfigDict(extra="forbid")


class IngestionJobStatusResponse(BaseModel):
    ingestion_job_id: int
    status: Literal["queued", "running", "succeeded", "failed", "partial"]
    created_at: datetime
    worker_id: str | None
    worker_started_at: datetime | None
    worker_completed_at: datetime | None
    error_detail: str | None
    ingestion_run_id: int | None

    model_config = ConfigDict(extra="forbid")


class DatasetVersionLifecycleResponse(BaseModel):
    dataset_version_id: int
    ingestion_status: str
    published_at: datetime | None

    model_config = ConfigDict(extra="forbid")


def get_ingestion_service() -> IngestionAdminService:
    return IngestionAdminService()


@router.post(
    "/uploads",
    response_model=IngestionUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_dataset(
    request: IngestionUploadRequest,
    service: IngestionAdminService = Depends(get_ingestion_service),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> IngestionUploadResponse:
    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="content_base64 must be valid base64.",
        ) from exc

    try:
        result = service.stage_upload(
            content=content,
            source_key=request.source_key,
            source_code=request.source_code,
            source_name=request.source_name,
            source_year=request.source_year,
            source_state=request.source_state,
            input_type=request.input_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_exception_detail(exc),
        ) from exc
    return IngestionUploadResponse(**result)


@router.post(
    "/runs",
    response_model=IngestionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_ingestion_run(
    request: IngestionRunRequest,
    session: Session = Depends(get_db_session),
    service: IngestionAdminService = Depends(get_ingestion_service),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> IngestionRunResponse:
    try:
        result = service.trigger_run(request, session)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_exception_detail(exc),
        ) from exc
    return IngestionRunResponse(**result)


@router.get("/runs/{ingestion_run_id}", response_model=IngestionRunStatusResponse)
def get_ingestion_run_status(
    ingestion_run_id: int,
    session: Session = Depends(get_db_session),
    service: IngestionAdminService = Depends(get_ingestion_service),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> IngestionRunStatusResponse:
    try:
        result = service.get_run_status(session, ingestion_run_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_exception_detail(exc),
        ) from exc
    return IngestionRunStatusResponse(**result)


@router.get(
    "/jobs/{ingestion_job_id}",
    response_model=IngestionJobStatusResponse,
)
def get_ingestion_job_status(
    ingestion_job_id: int,
    session: Session = Depends(get_db_session),
    service: IngestionAdminService = Depends(get_ingestion_service),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> IngestionJobStatusResponse:
    try:
        result = service.get_job_status(session, ingestion_job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_exception_detail(exc),
        ) from exc
    return IngestionJobStatusResponse(**result)


@router.post(
    "/dataset-versions/{dataset_version_id}/publish",
    response_model=DatasetVersionLifecycleResponse,
)
def publish_dataset_version(
    dataset_version_id: int,
    session: Session = Depends(get_db_session),
    service: IngestionAdminService = Depends(get_ingestion_service),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> DatasetVersionLifecycleResponse:
    try:
        result = service.publish_dataset_version(session, dataset_version_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_exception_detail(exc),
        ) from exc
    return DatasetVersionLifecycleResponse(**result)


@router.post(
    "/dataset-versions/{dataset_version_id}/unpublish",
    response_model=DatasetVersionLifecycleResponse,
)
def unpublish_dataset_version(
    dataset_version_id: int,
    session: Session = Depends(get_db_session),
    service: IngestionAdminService = Depends(get_ingestion_service),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> DatasetVersionLifecycleResponse:
    try:
        result = service.unpublish_dataset_version(session, dataset_version_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_exception_detail(exc),
        ) from exc
    return DatasetVersionLifecycleResponse(**result)


def _exception_detail(exc: Exception) -> str:
    if exc.args:
        return str(exc.args[0])
    return str(exc)

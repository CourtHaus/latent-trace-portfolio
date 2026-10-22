from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

HealthStatus = Literal["healthy", "warning", "critical"]
WarningSeverity = Literal["info", "warning", "critical"]
JobType = Literal["ingestion", "extraction", "geocoding"]


class OperatorSystemSnapshot(BaseModel):
    health: HealthStatus
    generated_at: datetime
    database_ok: bool
    environment: str

    model_config = ConfigDict(extra="forbid")


class OperatorDatasetSnapshot(BaseModel):
    version: str
    published_dataset_versions: int
    total_cases: int
    state_count: int
    source_count: int
    geocoded_cases: int
    geocoded_percent: float
    last_ingested_at: datetime | None
    last_published_at: datetime | None

    model_config = ConfigDict(extra="forbid")


class OperatorStatusCounts(BaseModel):
    queued: int
    running: int
    succeeded: int
    failed: int
    partial: int
    skipped: int

    model_config = ConfigDict(extra="forbid")


class OperatorPipelineSnapshot(BaseModel):
    ingestion: OperatorStatusCounts
    extraction: OperatorStatusCounts
    geocoding: OperatorStatusCounts
    stale_running_count: int
    old_queued_count: int

    model_config = ConfigDict(extra="forbid")


class OperatorWarning(BaseModel):
    severity: WarningSeverity
    code: str
    title: str
    detail: str

    model_config = ConfigDict(extra="forbid")


class OperatorFailureItem(BaseModel):
    job_type: JobType
    job_id: str
    status: str
    source_code: str | None
    case_id: int | None
    case_name: str | None
    error_detail: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = ConfigDict(extra="forbid")


class OperatorSourceSummary(BaseModel):
    code: str
    name: str
    state: str | None
    case_count: int
    geocoded_count: int
    geocoded_percent: float
    year_min: int | None
    year_max: int | None

    model_config = ConfigDict(extra="forbid")


class OperatorSnapshotResponse(BaseModel):
    system: OperatorSystemSnapshot
    dataset: OperatorDatasetSnapshot
    pipeline: OperatorPipelineSnapshot
    warnings: list[OperatorWarning]
    latest_failures: list[OperatorFailureItem]
    sources: list[OperatorSourceSummary]

    model_config = ConfigDict(extra="forbid")

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from casesignal.api.schemas.operator import (
    OperatorDatasetSnapshot,
    OperatorFailureItem,
    OperatorPipelineSnapshot,
    OperatorStatusCounts,
)
from casesignal.api.services.operator_snapshot import (
    _build_warnings,
    _derive_health,
    _format_dataset_version,
    _query_dataset,
    _query_latest_failures,
    _query_pipeline,
    _query_sources,
    _status_counts,
    get_operator_snapshot,
)


class FakeResult:
    def __init__(
        self,
        *,
        one: dict[str, Any] | None = None,
        all_rows: list[dict[str, Any]] | None = None,
        scalar: int | None = None,
    ) -> None:
        self._one = one
        self._all_rows = all_rows or []
        self._scalar = scalar

    def mappings(self) -> FakeResult:
        return self

    def one(self) -> dict[str, Any]:
        assert self._one is not None
        return self._one

    def all(self) -> list[dict[str, Any]]:
        return self._all_rows

    def scalar_one(self) -> int:
        assert self._scalar is not None
        return self._scalar


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.statements: list[str] = []

    def execute(self, statement: Any) -> FakeResult:
        self.statements.append(str(statement))
        return self.results.pop(0)


def _dataset_row() -> dict[str, Any]:
    return {
        "total_cases": 4,
        "geocoded_cases": 3,
        "state_count": 2,
        "source_count": 2,
        "published_dataset_versions": 1,
        "last_ingested_at": datetime(2026, 5, 20, tzinfo=timezone.utc),
        "last_published_at": datetime(2026, 5, 21, tzinfo=timezone.utc),
    }


def _failure_row() -> dict[str, Any]:
    return {
        "job_type": "ingestion",
        "job_id": "7",
        "status": "failed",
        "source_code": None,
        "case_id": None,
        "case_name": None,
        "error_detail": "boom",
        "created_at": datetime(2026, 5, 20, tzinfo=timezone.utc),
        "started_at": None,
        "completed_at": None,
    }


def test_format_dataset_version_uses_year_and_month() -> None:
    value = datetime(2026, 5, 20, tzinfo=timezone.utc)
    assert _format_dataset_version(value) == "v2026.05"


def test_derive_health_is_critical_when_critical_warning_exists() -> None:
    assert _derive_health(["critical", "warning"]) == "critical"


def test_derive_health_is_warning_when_only_warning_exists() -> None:
    assert _derive_health(["info", "warning"]) == "warning"


def test_derive_health_is_healthy_without_warnings() -> None:
    assert _derive_health([]) == "healthy"


def test_status_counts_raises_on_unexpected_status() -> None:
    with pytest.raises(ValueError, match="Unexpected operator job status: cancelled"):
        _status_counts([{"status": "cancelled", "count": 1}])


def test_build_warnings_flags_missing_published_dataset() -> None:
    warnings = _build_warnings(
        dataset=OperatorDatasetSnapshot(
            version="v0.0",
            published_dataset_versions=0,
            total_cases=0,
            state_count=0,
            source_count=0,
            geocoded_cases=0,
            geocoded_percent=0.0,
            last_ingested_at=None,
            last_published_at=None,
        ),
        pipeline=OperatorPipelineSnapshot(
            ingestion=OperatorStatusCounts(queued=0, running=0, succeeded=0, failed=0, partial=0, skipped=0),
            extraction=OperatorStatusCounts(queued=0, running=0, succeeded=0, failed=0, partial=0, skipped=0),
            geocoding=OperatorStatusCounts(queued=0, running=0, succeeded=0, failed=0, partial=0, skipped=0),
            stale_running_count=0,
            old_queued_count=0,
        ),
        latest_failures=[],
    )
    assert warnings[0].severity == "critical"
    assert warnings[0].code == "no_published_dataset"


def test_build_warnings_flags_failed_jobs_and_low_geocoding() -> None:
    warnings = _build_warnings(
        dataset=OperatorDatasetSnapshot(
            version="v2026.05",
            published_dataset_versions=2,
            total_cases=10,
            state_count=2,
            source_count=2,
            geocoded_cases=5,
            geocoded_percent=50.0,
            last_ingested_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
            last_published_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        ),
        pipeline=OperatorPipelineSnapshot(
            ingestion=OperatorStatusCounts(queued=0, running=0, succeeded=1, failed=1, partial=0, skipped=0),
            extraction=OperatorStatusCounts(queued=0, running=0, succeeded=1, failed=0, partial=0, skipped=0),
            geocoding=OperatorStatusCounts(queued=0, running=0, succeeded=1, failed=0, partial=0, skipped=0),
            stale_running_count=1,
            old_queued_count=2,
        ),
        latest_failures=[
            OperatorFailureItem(
                job_type="ingestion",
                job_id="7",
                status="failed",
                source_code="VSPCCD_VA",
                case_id=None,
                case_name=None,
                error_detail="boom",
                created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
                started_at=None,
                completed_at=None,
            )
        ],
    )
    codes = [warning.code for warning in warnings]
    assert codes == [
        "recent_failed_jobs",
        "stale_running_jobs",
        "old_queued_jobs",
        "low_geocoding_coverage",
    ]


def test_query_dataset_maps_row_and_counts_complete_coordinates() -> None:
    session = FakeSession([FakeResult(one=_dataset_row())])

    dataset = _query_dataset(session)  # type: ignore[arg-type]

    assert dataset.version == "v2026.05"
    assert dataset.total_cases == 4
    assert dataset.geocoded_cases == 3
    assert dataset.geocoded_percent == 75.0
    assert "c.latitude IS NOT NULL AND c.longitude IS NOT NULL" in session.statements[0]


def test_query_pipeline_maps_status_counts_and_queue_health() -> None:
    session = FakeSession(
        [
            FakeResult(scalar=1),
            FakeResult(scalar=2),
            FakeResult(all_rows=[{"status": "queued", "count": 3}, {"status": "succeeded", "count": 4}]),
            FakeResult(all_rows=[{"status": "running", "count": 5}]),
            FakeResult(all_rows=[{"status": "failed", "count": 6}]),
        ]
    )

    pipeline = _query_pipeline(session)  # type: ignore[arg-type]

    assert pipeline.stale_running_count == 1
    assert pipeline.old_queued_count == 2
    assert pipeline.ingestion.queued == 3
    assert pipeline.ingestion.succeeded == 4
    assert pipeline.extraction.running == 5
    assert pipeline.geocoding.failed == 6


def test_query_latest_failures_filters_to_recent_completion_window() -> None:
    session = FakeSession([FakeResult(all_rows=[_failure_row()])])

    failures = _query_latest_failures(session)  # type: ignore[arg-type]

    assert failures[0].job_id == "7"
    assert failures[0].error_detail == "boom"
    statement = session.statements[0]
    assert "INTERVAL '24 hours'" in statement
    assert "COALESCE(worker_completed_at, created_at) AS failure_at" in statement
    assert "COALESCE(j.worker_completed_at, j.created_at) AS failure_at" in statement
    assert "COALESCE(j.completed_at, j.created_at) AS failure_at" in statement
    assert "WHERE failure_at >= NOW() - INTERVAL '24 hours'" in statement
    assert "ORDER BY failure_at DESC" in statement
    assert "created_at >= NOW() - INTERVAL '24 hours'" not in statement


def test_query_sources_maps_rows_and_counts_complete_coordinates() -> None:
    session = FakeSession(
        [
            FakeResult(
                all_rows=[
                    {
                        "code": "VSPCCD_VA",
                        "name": "Virginia State Police",
                        "state": "VA",
                        "case_count": 5,
                        "geocoded_count": 4,
                        "year_min": 1980,
                        "year_max": 2026,
                    }
                ]
            )
        ]
    )

    sources = _query_sources(session)  # type: ignore[arg-type]

    assert sources[0].code == "VSPCCD_VA"
    assert sources[0].case_count == 5
    assert sources[0].geocoded_count == 4
    assert sources[0].geocoded_percent == 80.0
    assert sources[0].year_min == 1980
    assert "c.latitude IS NOT NULL AND c.longitude IS NOT NULL" in session.statements[0]


def test_get_operator_snapshot_assembles_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    session = FakeSession(
        [
            FakeResult(one=_dataset_row()),
            FakeResult(scalar=0),
            FakeResult(scalar=0),
            FakeResult(all_rows=[{"status": "succeeded", "count": 1}]),
            FakeResult(all_rows=[{"status": "succeeded", "count": 2}]),
            FakeResult(all_rows=[{"status": "succeeded", "count": 3}]),
            FakeResult(all_rows=[_failure_row()]),
            FakeResult(
                all_rows=[
                    {
                        "code": "VSPCCD_VA",
                        "name": "Virginia State Police",
                        "state": "VA",
                        "case_count": 4,
                        "geocoded_count": 3,
                        "year_min": 1990,
                        "year_max": 2026,
                    }
                ]
            ),
        ]
    )

    snapshot = get_operator_snapshot(session)  # type: ignore[arg-type]

    assert snapshot.system.environment == "dev"
    assert snapshot.system.health == "warning"
    assert snapshot.dataset.version == "v2026.05"
    assert snapshot.pipeline.ingestion.succeeded == 1
    assert snapshot.pipeline.extraction.succeeded == 2
    assert snapshot.pipeline.geocoding.succeeded == 3
    assert [warning.code for warning in snapshot.warnings] == [
        "recent_failed_jobs",
        "low_geocoding_coverage",
    ]
    assert snapshot.latest_failures[0].job_id == "7"
    assert snapshot.sources[0].code == "VSPCCD_VA"

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Literal, SupportsInt, cast

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.schemas.operator import (
    HealthStatus,
    OperatorDatasetSnapshot,
    OperatorFailureItem,
    OperatorPipelineSnapshot,
    OperatorSnapshotResponse,
    OperatorSourceSummary,
    OperatorStatusCounts,
    OperatorSystemSnapshot,
    OperatorWarning,
    WarningSeverity,
)

GEOCODING_WARNING_THRESHOLD_PERCENT = 80.0
RECENT_FAILURE_WINDOW_HOURS = 24
StatusCountRow = Mapping[str, str | SupportsInt]


def _format_dataset_version(value: datetime | None) -> str:
    if value is None:
        return "v0.0"
    return f"v{value.year}.{value.month:02d}"


def _status_counts(rows: Iterable[StatusCountRow]) -> OperatorStatusCounts:
    counts = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0, "partial": 0, "skipped": 0}
    for row in rows:
        status = str(row["status"])
        if status not in counts:
            raise ValueError(f"Unexpected operator job status: {status}")
        counts[status] = int(row["count"])
    return OperatorStatusCounts(**counts)


def _derive_health(severities: list[WarningSeverity]) -> HealthStatus:
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "healthy"


def _build_warnings(
    *,
    dataset: OperatorDatasetSnapshot,
    pipeline: OperatorPipelineSnapshot,
    latest_failures: list[OperatorFailureItem],
) -> list[OperatorWarning]:
    warnings: list[OperatorWarning] = []
    if dataset.published_dataset_versions == 0 or dataset.total_cases == 0:
        warnings.append(
            OperatorWarning(
                severity="critical",
                code="no_published_dataset",
                title="No published dataset",
                detail="No published dataset with live cases is available.",
            )
        )
    if latest_failures:
        warnings.append(
            OperatorWarning(
                severity="warning",
                code="recent_failed_jobs",
                title="Recent failed jobs",
                detail=f"{len(latest_failures)} failed job or run records need review.",
            )
        )
    if pipeline.stale_running_count > 0:
        warnings.append(
            OperatorWarning(
                severity="warning",
                code="stale_running_jobs",
                title="Stale running jobs",
                detail=f"{pipeline.stale_running_count} running job records are older than the recovery threshold.",
            )
        )
    if pipeline.old_queued_count > 0:
        warnings.append(
            OperatorWarning(
                severity="warning",
                code="old_queued_jobs",
                title="Old queued jobs",
                detail=f"{pipeline.old_queued_count} queued job records have been waiting longer than expected.",
            )
        )
    if dataset.total_cases > 0 and dataset.geocoded_percent < GEOCODING_WARNING_THRESHOLD_PERCENT:
        warnings.append(
            OperatorWarning(
                severity="warning",
                code="low_geocoding_coverage",
                title="Low geocoding coverage",
                detail=(
                    f"Geocoding coverage is {dataset.geocoded_percent:.1f}%, below the "
                    f"{GEOCODING_WARNING_THRESHOLD_PERCENT:.0f}% operator threshold."
                ),
            )
        )
    return warnings


def _query_dataset(session: Session) -> OperatorDatasetSnapshot:
    row = (
        session.execute(
            text(
                "SELECT"
                " COUNT(c.case_id)::int AS total_cases,"
                " COUNT(*) FILTER"
                " (WHERE c.latitude IS NOT NULL AND c.longitude IS NOT NULL)::int"
                " AS geocoded_cases,"
                " COUNT(DISTINCT c.state)::int AS state_count,"
                " COUNT(DISTINCT ss.source_system_id)::int AS source_count,"
                " COUNT(DISTINCT dv.dataset_version_id)::int AS published_dataset_versions,"
                " MAX(dv.created_at) AS last_ingested_at,"
                " MAX(COALESCE(dv.published_at, dv.created_at)) AS last_published_at"
                " FROM etl.dataset_version dv"
                " JOIN etl.source_system ss USING (source_system_id)"
                " LEFT JOIN cold_case.cases c USING (dataset_version_id)"
                " WHERE dv.ingestion_status = 'published'"
            )
        )
        .mappings()
        .one()
    )
    total_cases = int(row["total_cases"] or 0)
    geocoded_cases = int(row["geocoded_cases"] or 0)
    geocoded_percent = (geocoded_cases / total_cases * 100.0) if total_cases else 0.0
    return OperatorDatasetSnapshot(
        version=_format_dataset_version(row["last_ingested_at"]),
        published_dataset_versions=int(row["published_dataset_versions"] or 0),
        total_cases=total_cases,
        state_count=int(row["state_count"] or 0),
        source_count=int(row["source_count"] or 0),
        geocoded_cases=geocoded_cases,
        geocoded_percent=round(geocoded_percent, 1),
        last_ingested_at=row["last_ingested_at"],
        last_published_at=row["last_published_at"],
    )


# Tables whose status columns this snapshot is allowed to aggregate. The set
# is small and known statically; SQL interpolation of the table name below is
# safe because we reject anything outside this allowlist before it reaches
# psycopg. Literal type also gives mypy a chance to catch unknown call sites.
_StatusCountTable = Literal[
    "etl.ingestion_job",
    "cold_case.extraction_job",
    "cold_case.geocoding_job",
]
_ALLOWED_STATUS_COUNT_TABLES: frozenset[str] = frozenset(
    {"etl.ingestion_job", "cold_case.extraction_job", "cold_case.geocoding_job"},
)


def _query_status_counts(
    session: Session, table_name: _StatusCountTable
) -> OperatorStatusCounts:
    if table_name not in _ALLOWED_STATUS_COUNT_TABLES:
        raise ValueError(
            f"_query_status_counts: table_name {table_name!r} not in allowlist"
        )
    rows = (
        session.execute(
            text(
                f"SELECT status, COUNT(*)::int AS count FROM {table_name} "
                "GROUP BY status ORDER BY status"
            )
        )
        .mappings()
        .all()
    )
    return _status_counts(cast(Iterable[StatusCountRow], rows))


def _query_pipeline(session: Session) -> OperatorPipelineSnapshot:
    stale_running_count = int(
        session.execute(
            text(
                "SELECT"
                " (SELECT COUNT(*) FROM etl.ingestion_job"
                "   WHERE status='running' AND worker_started_at < NOW() - INTERVAL '2 hours')"
                " + (SELECT COUNT(*) FROM cold_case.extraction_job"
                "   WHERE status='running' AND worker_started_at < NOW() - INTERVAL '2 hours')"
                " + (SELECT COUNT(*) FROM cold_case.geocoding_job"
                "   WHERE status='running' AND worker_started_at < NOW() - INTERVAL '2 hours')"
            )
        ).scalar_one()
        or 0
    )
    old_queued_count = int(
        session.execute(
            text(
                "SELECT"
                " (SELECT COUNT(*) FROM etl.ingestion_job"
                "   WHERE status='queued' AND created_at < NOW() - INTERVAL '24 hours')"
                " + (SELECT COUNT(*) FROM cold_case.extraction_job"
                "   WHERE status='queued' AND created_at < NOW() - INTERVAL '24 hours')"
                " + (SELECT COUNT(*) FROM cold_case.geocoding_job"
                "   WHERE status='queued' AND created_at < NOW() - INTERVAL '24 hours')"
            )
        ).scalar_one()
        or 0
    )
    return OperatorPipelineSnapshot(
        ingestion=_query_status_counts(session, "etl.ingestion_job"),
        extraction=_query_status_counts(session, "cold_case.extraction_job"),
        geocoding=_query_status_counts(session, "cold_case.geocoding_job"),
        stale_running_count=stale_running_count,
        old_queued_count=old_queued_count,
    )


def _query_latest_failures(session: Session) -> list[OperatorFailureItem]:
    recent_window = f"{RECENT_FAILURE_WINDOW_HOURS} hours"
    rows = (
        session.execute(
            text(
                "SELECT"
                " job_type,"
                " job_id,"
                " status,"
                " source_code,"
                " case_id,"
                " case_name,"
                " error_detail,"
                " created_at,"
                " started_at,"
                " completed_at"
                " FROM ("
                " SELECT 'ingestion' AS job_type,"
                "        ingestion_job_id::text AS job_id,"
                "        status,"
                "        NULL::text AS source_code,"
                "        NULL::bigint AS case_id,"
                "        NULL::text AS case_name,"
                "        error_detail,"
                "        created_at,"
                "        worker_started_at AS started_at,"
                "        worker_completed_at AS completed_at,"
                "        COALESCE(worker_completed_at, created_at) AS failure_at"
                "   FROM etl.ingestion_job"
                "  WHERE status IN ('failed', 'partial')"
                " UNION ALL"
                " SELECT 'extraction' AS job_type,"
                "        j.extraction_job_id::text AS job_id,"
                "        j.status,"
                "        ss.source_code,"
                "        c.case_id,"
                "        c.case_name,"
                "        j.error_detail,"
                "        j.created_at,"
                "        j.worker_started_at AS started_at,"
                "        j.worker_completed_at AS completed_at,"
                "        COALESCE(j.worker_completed_at, j.created_at) AS failure_at"
                "   FROM cold_case.extraction_job j"
                "   JOIN cold_case.cases c USING (case_id)"
                "   JOIN etl.dataset_version dv USING (dataset_version_id)"
                "   JOIN etl.source_system ss USING (source_system_id)"
                "  WHERE j.status = 'failed'"
                " UNION ALL"
                " SELECT 'geocoding' AS job_type,"
                "        j.geocoding_job_id::text AS job_id,"
                "        j.status,"
                "        ss.source_code,"
                "        c.case_id,"
                "        c.case_name,"
                "        j.error_detail,"
                "        j.created_at,"
                "        j.started_at,"
                "        j.completed_at,"
                "        COALESCE(j.completed_at, j.created_at) AS failure_at"
                "   FROM cold_case.geocoding_job j"
                "   JOIN cold_case.cases c USING (case_id)"
                "   JOIN etl.dataset_version dv USING (dataset_version_id)"
                "   JOIN etl.source_system ss USING (source_system_id)"
                "  WHERE j.status = 'failed'"
                ") failures"
                f" WHERE failure_at >= NOW() - INTERVAL '{recent_window}'"
                " ORDER BY failure_at DESC"
                " LIMIT 20"
            )
        )
        .mappings()
        .all()
    )
    return [OperatorFailureItem(**row) for row in rows]


def _query_sources(session: Session) -> list[OperatorSourceSummary]:
    rows = (
        session.execute(
            text(
                "SELECT"
                " ss.source_code AS code,"
                " ss.source_name AS name,"
                " MAX(dv.source_state) AS state,"
                " COUNT(c.case_id)::int AS case_count,"
                " COUNT(*) FILTER"
                " (WHERE c.latitude IS NOT NULL AND c.longitude IS NOT NULL)::int"
                " AS geocoded_count,"
                " MIN(EXTRACT(YEAR FROM c.incident_date))::int AS year_min,"
                " MAX(EXTRACT(YEAR FROM c.incident_date))::int AS year_max"
                " FROM etl.source_system ss"
                " JOIN etl.dataset_version dv USING (source_system_id)"
                " JOIN cold_case.cases c USING (dataset_version_id)"
                " WHERE dv.ingestion_status = 'published'"
                " GROUP BY ss.source_system_id, ss.source_code, ss.source_name"
                " ORDER BY COUNT(c.case_id) DESC, ss.source_code"
            )
        )
        .mappings()
        .all()
    )
    sources: list[OperatorSourceSummary] = []
    for row in rows:
        case_count = int(row["case_count"] or 0)
        geocoded_count = int(row["geocoded_count"] or 0)
        sources.append(
            OperatorSourceSummary(
                code=row["code"],
                name=row["name"],
                state=row["state"],
                case_count=case_count,
                geocoded_count=geocoded_count,
                geocoded_percent=round(
                    (geocoded_count / case_count * 100.0) if case_count else 0.0, 1
                ),
                year_min=row["year_min"],
                year_max=row["year_max"],
            )
        )
    return sources


def get_operator_snapshot(session: Session) -> OperatorSnapshotResponse:
    generated_at = datetime.now(timezone.utc)
    dataset = _query_dataset(session)
    pipeline = _query_pipeline(session)
    latest_failures = _query_latest_failures(session)
    sources = _query_sources(session)
    warnings = _build_warnings(dataset=dataset, pipeline=pipeline, latest_failures=latest_failures)
    health = _derive_health([warning.severity for warning in warnings])
    return OperatorSnapshotResponse(
        system=OperatorSystemSnapshot(
            health=health,
            generated_at=generated_at,
            database_ok=True,
            environment=os.environ.get("APP_ENV", "production"),
        ),
        dataset=dataset,
        pipeline=pipeline,
        warnings=warnings,
        latest_failures=latest_failures,
        sources=sources,
    )

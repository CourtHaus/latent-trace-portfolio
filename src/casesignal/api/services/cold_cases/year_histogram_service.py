"""Per-year incident counts — drives the landing's decade histogram.

Returns one bucket per year that has at least one dated case (ascending), plus
the count of undated cases. The frontend aggregates years into decades.

Both queries gate on `etl.dataset_version.ingestion_status = 'published'`
(SEC-2026-05-31-A): this backs a public, 1-hour-cached route, so an operator
takedown (unpublish → 'archived') must not leak the archived dataset's per-year
counts.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.schemas.cold_cases import YearBucket, YearHistogramResponse

_PUB_JOIN = (
    " FROM cold_case.cases AS cases"
    " JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id"
    " AND dv.ingestion_status = 'published'"
)


def get_year_histogram(session: Session) -> YearHistogramResponse:
    rows = session.execute(
        text(
            "SELECT EXTRACT(YEAR FROM cases.incident_date)::int AS year, COUNT(*) AS count"
            + _PUB_JOIN
            + " WHERE cases.incident_date IS NOT NULL"
            " GROUP BY year"
            " ORDER BY year"
        )
    ).mappings().all()
    undated = session.execute(
        text("SELECT COUNT(*)" + _PUB_JOIN + " WHERE cases.incident_date IS NULL")
    ).scalar_one()
    buckets = [YearBucket(year=r["year"], count=r["count"]) for r in rows]
    total_dated = sum(b.count for b in buckets)
    return YearHistogramResponse(
        buckets=buckets,
        total_dated=total_dated,
        undated=undated,
    )

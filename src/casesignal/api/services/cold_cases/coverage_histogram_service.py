"""Per-(state, decade) published-case counts — drives the coverage heatmap.

Mirrors year_histogram_service: gates on dataset_version.ingestion_status =
'published' so an operator takedown never leaks archived counts. Rows with a
NULL incident_date or NULL source_state are excluded.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.schemas.cold_cases import CoverageBucket, CoverageHistogramResponse
from casesignal.api.services.cold_cases.year_histogram_service import _PUB_JOIN


def get_coverage_histogram(session: Session) -> CoverageHistogramResponse:
    # Group by dv.source_state (the dataset-level state tag), consistent with
    # how /filter-options groups states — intentional, not cases.state.
    rows = session.execute(
        text(
            "SELECT dv.source_state AS state,"
            " (FLOOR(EXTRACT(YEAR FROM cases.incident_date) / 10) * 10)::int AS decade,"
            " COUNT(*) AS count"
            + _PUB_JOIN
            + " WHERE cases.incident_date IS NOT NULL AND dv.source_state IS NOT NULL"
            " GROUP BY dv.source_state,"
            " (FLOOR(EXTRACT(YEAR FROM cases.incident_date) / 10) * 10)::int"
            " ORDER BY state, decade"
        )
    ).mappings().all()
    return CoverageHistogramResponse(
        buckets=[
            CoverageBucket(state=r["state"], decade=r["decade"], count=r["count"])
            for r in rows
        ]
    )

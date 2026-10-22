"""Per-source aggregate stats — drives the methodology page coverage view."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.schemas.cold_cases import SourcesSummaryResponse, SourceSummaryItem


def get_sources_summary(session: Session) -> SourcesSummaryResponse:
    """One row per source_system that has at least one case ingested.

    Aggregates across all dataset_version rows that point at the same source.
    state is taken from MAX(source_state); in practice every source maps to
    a single state but the column is per-dataset-version. geocoded_count
    counts cases with a non-null latitude — covers both ladder-geocoded
    rows (geocode_precision set) and source-provided coordinates (e.g. VA,
    where VSPCCD ships lat/lon and the geocoding ladder is skipped).
    """
    rows = (
        session.execute(
            text(
                "SELECT"
                "  ss.source_code AS code,"
                "  ss.source_name AS name,"
                "  MAX(dv.source_state) AS state,"
                "  COUNT(c.case_id) AS case_count,"
                "  COUNT(c.latitude) AS geocoded_count,"
                "  MIN(EXTRACT(YEAR FROM c.incident_date))::int AS year_min,"
                "  MAX(EXTRACT(YEAR FROM c.incident_date))::int AS year_max"
                " FROM etl.source_system ss"
                " JOIN etl.dataset_version dv USING (source_system_id)"
                " JOIN cold_case.cases c USING (dataset_version_id)"
                # Gate to published versions (SEC-2026-05-31-A): an archived
                # dataset must drop out of the public methodology coverage view.
                " WHERE dv.ingestion_status = 'published'"
                " GROUP BY ss.source_system_id, ss.source_code, ss.source_name"
                " ORDER BY COUNT(c.case_id) DESC, ss.source_code"
            )
        )
        .mappings()
        .all()
    )
    return SourcesSummaryResponse(
        data=[
            SourceSummaryItem(
                code=r["code"],
                name=r["name"],
                state=r["state"],
                case_count=r["case_count"],
                geocoded_count=r["geocoded_count"],
                year_min=r["year_min"],
                year_max=r["year_max"],
            )
            for r in rows
        ]
    )

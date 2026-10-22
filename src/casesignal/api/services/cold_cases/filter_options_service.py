"""Filter-options endpoint — DISTINCTed dimensions feeding the sidebar.

Each dimension has its own `_query_*` helper. `get_filter_options` is the
orchestrator that calls each and assembles the `FilterOptionsResponse`.
Splitting per-dimension makes each query individually testable + readable.

Every helper joins through to `etl.dataset_version` and constrains
`ingestion_status = 'published'` (SEC-2026-05-31-A). These distinct-value lists
back a public, 1-hour-cached endpoint, so without the gate an operator takedown
(unpublish → 'archived') would still leak the archived dataset's filter values —
and the long cache would prolong the leak.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.schemas.cold_cases import (
    DatasetBlock,
    FilterOptionsResponse,
    SourceSystemOption,
    YearRange,
)
from casesignal.api.services.cold_cases.filters import (
    GENDER_CANONICAL_MAP,
    canonical_race,
)

# Join fragments that restrict a base-table query to published dataset versions.
# `_PUB_FROM_CASES` is for queries rooted at cold_case.cases (alias `cases`);
# the victim / extraction helpers join to cases first, then reuse the same gate.
_PUB_FROM_CASES = (
    " FROM cold_case.cases AS cases"
    " JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id"
    " AND dv.ingestion_status = 'published'"
)


def _query_case_types(session: Session) -> list[str]:
    return [
        r[0]
        for r in session.execute(
            text(
                "SELECT cases.case_type" + _PUB_FROM_CASES + " WHERE cases.case_type IS NOT NULL"
                " GROUP BY cases.case_type"
                ' ORDER BY LOWER(cases.case_type) COLLATE "C", cases.case_type'
            )
        ).all()
    ]


def _query_cities(session: Session) -> list[str]:
    return [
        r[0]
        for r in session.execute(
            text(
                "SELECT cases.city" + _PUB_FROM_CASES + " WHERE cases.city IS NOT NULL"
                " GROUP BY cases.city"
                ' ORDER BY LOWER(cases.city) COLLATE "C", cases.city'
            )
        ).all()
    ]


def _query_genders(session: Session) -> list[str]:
    """Canonicalize gender to {M, F, unknown}.

    Both 'M'/'male' and 'F'/'female' exist in storage historically; surface only
    the canonical form to clients.
    """
    raw_genders = [
        r[0]
        for r in session.execute(
            text(
                "SELECT DISTINCT v.gender"
                " FROM cold_case.victim v"
                " JOIN cold_case.cases cases ON cases.case_id = v.case_id"
                " JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id"
                " AND dv.ingestion_status = 'published'"
                " WHERE v.gender IS NOT NULL"
            )
        ).all()
    ]
    return sorted(
        {
            GENDER_CANONICAL_MAP[g.lower()]
            for g in raw_genders
            if g.lower() in GENDER_CANONICAL_MAP
        },
        key=str.lower,
    )


def _query_races(session: Session) -> list[str]:
    """Distinct canonical victim-race buckets present in published data.

    Source agencies spell race ~24 different ways for a handful of concepts;
    this folds the raw values to the FBI/NIBRS canonical buckets via
    `canonical_race` (see filters.RACE_CANONICAL_MAP) so the filter facet doesn't
    fragment and selecting a bucket matches every raw spelling. Deterministic
    synonym mapping over source-provided values — never inference; raw values stay
    on the victim row. Returned alphabetically (case-insensitive) to match the
    sort contract shared with the other filter-option arrays.
    """
    raw_values = (
        session.execute(
            text(
                "SELECT DISTINCT v.race"
                "   FROM cold_case.victim v"
                "   JOIN cold_case.cases cases ON cases.case_id = v.case_id"
                "   JOIN etl.dataset_version dv"
                "     ON dv.dataset_version_id = cases.dataset_version_id"
                "    AND dv.ingestion_status = 'published'"
                "  WHERE v.race IS NOT NULL"
            )
        )
        .scalars()
        .all()
    )
    buckets = {canonical_race(r) for r in raw_values}
    return sorted(buckets, key=str.lower)


def _query_states(session: Session) -> list[str]:
    return [
        r[0]
        for r in session.execute(
            text(
                "SELECT cases.state" + _PUB_FROM_CASES + " WHERE cases.state IS NOT NULL"
                " GROUP BY cases.state"
                ' ORDER BY LOWER(cases.state) COLLATE "C", cases.state'
            )
        ).all()
    ]


def _query_weapons(session: Session) -> list[str]:
    return [
        r[0]
        for r in session.execute(
            text(
                "SELECT DISTINCT ext.weapon"
                " FROM cold_case.case_extractions_current ext"
                " JOIN cold_case.cases cases ON cases.case_id = ext.case_id"
                " JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id"
                " AND dv.ingestion_status = 'published'"
                " WHERE ext.weapon IS NOT NULL"
                " ORDER BY ext.weapon"
            )
        ).all()
    ]


def _query_location_types(session: Session) -> list[str]:
    return [
        r[0]
        for r in session.execute(
            text(
                "SELECT DISTINCT ext.location_type"
                " FROM cold_case.case_extractions_current ext"
                " JOIN cold_case.cases cases ON cases.case_id = ext.case_id"
                " JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id"
                " AND dv.ingestion_status = 'published'"
                " WHERE ext.location_type IS NOT NULL"
                " ORDER BY ext.location_type"
            )
        ).all()
    ]


def _query_source_systems(session: Session) -> list[SourceSystemOption]:
    return [
        SourceSystemOption(code=r["source_code"], name=r["source_name"])
        for r in session.execute(
            text(
                "SELECT ss.source_code, ss.source_name"
                "  FROM etl.source_system ss"
                "  JOIN etl.dataset_version dv USING (source_system_id)"
                "  JOIN cold_case.cases c USING (dataset_version_id)"
                " WHERE dv.ingestion_status = 'published'"
                " GROUP BY ss.source_code, ss.source_name"
                ' ORDER BY LOWER(ss.source_name) COLLATE "C", ss.source_name'
            )
        )
        .mappings()
        .all()
    ]


def _query_year_range(session: Session) -> YearRange:
    row = (
        session.execute(
            text(
                "SELECT MIN(EXTRACT(YEAR FROM cases.incident_date))::int AS ymin,"
                "       MAX(EXTRACT(YEAR FROM cases.incident_date))::int AS ymax"
                + _PUB_FROM_CASES
            )
        )
        .mappings()
        .one()
    )
    return YearRange(min=row["ymin"], max=row["ymax"])


def _query_dataset_block(session: Session) -> DatasetBlock:
    """Latest PUBLISHED dataset_version row, formatted as 'v<YEAR>.<MONTH-2digit>'.

    Version derived from `created_at` (row insert time) rather than
    `published_at` since the latter is nullable for unpublished drafts.
    Restricted to published versions so an archived/draft version never sets the
    public "data version" indicator (SEC-2026-05-31-A).
    """
    row = (
        session.execute(
            text(
                "SELECT created_at FROM etl.dataset_version"
                " WHERE ingestion_status = 'published'"
                " ORDER BY created_at DESC LIMIT 1"
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["created_at"] is None:
        return DatasetBlock(version="v0.0", last_ingested=None)
    ingested = row["created_at"]
    return DatasetBlock(version=f"v{ingested.year}.{ingested.month:02d}", last_ingested=ingested)


def get_filter_options(session: Session) -> FilterOptionsResponse:
    """Return the dataset's distinct values for filter option lists.

    Arrays are alphabetically sorted (case-insensitive via LOWER()). year_range
    bounds come from MIN/MAX of incident_date's YEAR extract; both may be NULL
    if the dataset is empty or has no dated cases.

    Orchestrator only — each filter dimension is built by its own helper
    (`_query_*` functions above). Each helper is individually testable + readable.
    """
    return FilterOptionsResponse(
        case_types=_query_case_types(session),
        cities=_query_cities(session),
        genders=_query_genders(session),
        races=_query_races(session),
        states=_query_states(session),
        weapons=_query_weapons(session),
        location_types=_query_location_types(session),
        source_systems=_query_source_systems(session),
        year_range=_query_year_range(session),
        dataset=_query_dataset_block(session),
    )

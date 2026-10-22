"""Per-facet case counts — drives the filter rail counts + jurisdiction bars.

Counts are FACETED: each value's count reflects all *other* active filters but
NOT the facet's own selection. So toggling one value in a multi-select facet
(e.g. case_type=homicide) doesn't zero out its siblings — the user still sees
how many cases each unselected value would add. With no filters active this
reduces to corpus-wide totals (what the landing jurisdiction bars want).

Each facet runs the shared FILTER_WHERE with its own dimension's bind param set
to NULL (which disables that one condition), grouped by the facet column.
`total` / `geocoded` apply ALL filters (no exclusion).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.schemas.cold_cases import FacetCount, FacetCountsResponse
from casesignal.api.services.cold_cases.filters import (
    GENDER_CANONICAL_MAP,
    build_filter_params,
    canonical_race,
    ext_needed,
    filter_from,
    filter_where,
)


def _scoped_col_counts(
    session: Session,
    *,
    group_col: str,
    own_key: str,
    params: dict[str, Any],
    extra: str = "",
    include_ext: bool = True,
) -> list[FacetCount]:
    """GROUP BY one case-level column, excluding the facet's own selection.

    `own_key` is the filter bind param for this dimension; binding it to NULL
    disables that condition so siblings stay visible. All joins are 1:1 with a
    case, so COUNT(*) counts distinct cases. include_ext must be True when
    group_col references ext.* (weapon/location_type facets) or when a
    weapon/location filter remains active.
    """
    scoped = {**params, own_key: None}
    extra_sql = f" AND {extra}" if extra else ""
    rows = (
        session.execute(
            text(
                f"SELECT {group_col} AS value, COUNT(*) AS count"  # noqa: S608 - group_col is a literal
                + filter_from(include_ext)
                + filter_where(include_ext)
                + f" AND {group_col} IS NOT NULL{extra_sql}"
                + f" GROUP BY {group_col}"
                + f" ORDER BY COUNT(*) DESC, {group_col}"
            ),
            scoped,
        )
        .mappings()
        .all()
    )
    return [FacetCount(value=r["value"], count=r["count"]) for r in rows]


def _scoped_gender_counts(
    session: Session, params: dict[str, Any], *, include_ext: bool = True
) -> list[FacetCount]:
    """Distinct cases per canonical victim gender ({M, F, ...}).

    Excludes the gender selection (keeps race + every other filter). Joins the
    grouped victim under alias `gv` so it never collides with the `v` alias in
    FILTER_WHERE's EXISTS subqueries. A case with multiple same-gender victims
    counts once; values outside GENDER_CANONICAL_MAP are dropped.
    """
    scoped = {**params, "gender": None}
    rows = session.execute(
        text(
            "SELECT cases.case_id AS case_id, LOWER(gv.gender) AS g"
            + filter_from(include_ext)
            + " JOIN cold_case.victim gv ON gv.case_id = cases.case_id AND gv.gender IS NOT NULL"
            + filter_where(include_ext)
        ),
        scoped,
    ).all()
    per_canon: dict[str, set[int]] = {}
    for case_id, g in rows:
        canon = GENDER_CANONICAL_MAP.get(g)
        if canon is None:
            continue
        per_canon.setdefault(canon, set()).add(case_id)
    return [
        FacetCount(value=canon, count=len(case_ids))
        for canon, case_ids in sorted(per_canon.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


def _scoped_race_counts(
    session: Session, params: dict[str, Any], *, include_ext: bool = True
) -> list[FacetCount]:
    """Distinct cases per canonical victim race.

    Excludes the race selection (keeps gender + every other filter). Mirrors
    filter_options_service._query_races: raw source spellings fold to the
    FBI/NIBRS canonical buckets via `canonical_race`, so the value strings match
    the rail's race options exactly and a case is counted once per bucket even if
    a synonym repeats. Race is source-provided; this only counts, never infers.
    """
    # Drop BOTH race params (positive + the "Other" complement exclude) so the
    # race facet ignores its own selection — standard faceted-nav behavior.
    scoped = {**params, "race": None, "race_other_exclude": None}
    rows = session.execute(
        text(
            "SELECT cases.case_id AS case_id, rv.race AS race"
            + filter_from(include_ext)
            + " JOIN cold_case.victim rv ON rv.case_id = cases.case_id AND rv.race IS NOT NULL"
            + filter_where(include_ext)
        ),
        scoped,
    ).all()
    cases: dict[str, set[int]] = {}
    for case_id, race in rows:
        cases.setdefault(canonical_race(race), set()).add(case_id)
    return [
        FacetCount(value=bucket, count=len(case_ids))
        for bucket, case_ids in sorted(cases.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


def get_facet_counts(
    session: Session,
    *,
    case_type: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    city: str | None = None,
    state: str | None = None,
    gender: list[str] | None = None,
    race: list[str] | None = None,
    weapon: list[str] | None = None,
    location_type: list[str] | None = None,
    source_system: list[str] | None = None,
    precision: list[str] | None = None,
    q: str | None = None,
) -> FacetCountsResponse:
    """Faceted case counts per filter value, plus geocoded + total scalars.

    Each facet excludes its own selection; total/geocoded apply all filters.
    Called with no arguments (landing) it returns corpus-wide totals.
    """
    params = build_filter_params(
        case_type=case_type,
        year_min=year_min,
        year_max=year_max,
        city=city,
        state=state,
        gender=gender,
        race=race,
        weapon=weapon,
        location_type=location_type,
        source_system=source_system,
        precision=precision,
        q=q,
    )
    # Only the queries that filter on or group by the extraction overlay need
    # the case_extractions_current join. total/geocoded and the non-MO facets
    # need it only when a weapon/location filter is still active; the weapon and
    # location_type facets group on ext.* so they always need it.
    needs_ext = ext_needed(weapon, location_type)
    total = session.execute(
        text("SELECT COUNT(*)" + filter_from(needs_ext) + filter_where(needs_ext)),
        params,
    ).scalar_one()
    geocoded = session.execute(
        text(
            "SELECT COUNT(cases.latitude)"
            + filter_from(needs_ext)
            + filter_where(needs_ext)
        ),
        params,
    ).scalar_one()
    return FacetCountsResponse(
        case_type=_scoped_col_counts(
            session, group_col="cases.case_type", own_key="case_type",
            params=params, include_ext=needs_ext,
        ),
        state=_scoped_col_counts(
            session, group_col="cases.state", own_key="state",
            params=params, include_ext=needs_ext,
        ),
        gender=_scoped_gender_counts(session, params, include_ext=needs_ext),
        race=_scoped_race_counts(session, params, include_ext=needs_ext),
        precision=_scoped_col_counts(
            session,
            group_col="cases.geocode_precision",
            own_key="precision",
            params=params,
            extra="cases.geocode_precision <> 'failed'",
            include_ext=needs_ext,
        ),
        weapon=_scoped_col_counts(
            session, group_col="ext.weapon", own_key="weapon",
            params=params, include_ext=True,
        ),
        location_type=_scoped_col_counts(
            session, group_col="ext.location_type", own_key="location_type",
            params=params, include_ext=True,
        ),
        source_system=_scoped_col_counts(
            session, group_col="ss.source_code", own_key="source_codes",
            params=params, include_ext=needs_ext,
        ),
        geocoded=geocoded,
        total=total,
    )

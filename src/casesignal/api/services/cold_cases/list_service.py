"""List endpoint query — filtered + sorted + paginated, with extraction overlay."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.schemas.cold_cases import ColdCaseListItem, SortOrder
from casesignal.api.services.cold_cases.filters import (
    PUBLISHED_ONLY,
    SORT_CLAUSES,
    build_filter_params,
    ext_needed,
    filter_from,
    filter_where,
)


def list_cold_cases(
    session: Session,
    *,
    limit: int,
    offset: int,
    sort: SortOrder,
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
) -> tuple[list[ColdCaseListItem], int, int]:
    """Return (rows, total, total_unfiltered).

    total is filter-scoped; total_unfiltered is always the global COUNT(*).

    MO filter semantics (weapon, location_type): a LEFT JOIN to
    cold_case.case_extractions_current is always present so list items
    receive weapon / weapon_low_confidence / location_type /
    location_type_low_confidence columns. When no MO filter is active,
    cases without an extraction row come back with NULL extraction
    fields (cards render no badge). When a MO filter IS active,
    `WHERE weapon = ANY(:weapon)` excludes NULL rows by SQL semantics
    (NULL never equals anything) — un-extracted cases silently drop
    from results, which is the desired behavior.

    Gender / race normalization: the API surfaces canonical gender
    {M, F, unknown} and case-folded race, but storage still has the
    full raw set ('male', 'M', 'Asian', 'asian', ...). Expand gender to
    all source forms and lowercase race input so the SQL match works
    regardless of which case/abbreviation the client sends.
    """
    # total_unfiltered is the PUBLIC corpus size, so it must exclude
    # non-published dataset versions (SEC-2026-05-31-A) — join + gate rather
    # than a bare COUNT(*).
    total_unfiltered = (
        session.execute(
            text(
                "SELECT COUNT(*) FROM cold_case.cases AS cases"
                " JOIN etl.dataset_version dv"
                " ON dv.dataset_version_id = cases.dataset_version_id"
                f" AND {PUBLISHED_ONLY}"
            )
        ).scalar()
        or 0
    )

    params: dict[str, Any] = build_filter_params(
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

    # The total count only touches the extraction overlay when a weapon/location
    # filter is active; otherwise omit the view join (1:1, never changes COUNT).
    needs_ext = ext_needed(weapon, location_type)
    total = (
        session.execute(
            text("SELECT COUNT(*)" + filter_from(needs_ext) + filter_where(needs_ext)),
            params,
        ).scalar()
        or 0
    )

    # The list rows SELECT ext columns, so they always need the join.
    where_clause = filter_where(include_ext=True)

    rows = (
        session.execute(
            text(f"""
        SELECT
          cases.case_id,
          cases.slug,
          cases.source_case_id,
          cases.case_name,
          cases.case_type,
          cases.incident_date,
          cases.city,
          cases.state,
          NULLIF(
            TRIM(
              COALESCE(primary_victim.first_name, '')
              || ' '
              || COALESCE(primary_victim.last_name, '')
            ),
            ''
          ) AS victim_primary_name,
          primary_victim.gender AS victim_primary_gender,
          primary_victim.age_num AS victim_primary_age,
          primary_victim.race AS victim_primary_race,
          ext.weapon AS weapon,
          COALESCE(ext.weapon_low_confidence, FALSE) AS weapon_low_confidence,
          ext.location_type AS location_type,
          COALESCE(ext.location_type_low_confidence, FALSE) AS location_type_low_confidence,
          cases.geocode_precision
          FROM cold_case.cases AS cases
          LEFT JOIN cold_case.case_extractions_current ext
            ON ext.case_id = cases.case_id AND ext.prompt_tier = 1
          JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id
            AND dv.ingestion_status = 'published'
          JOIN etl.source_system ss ON ss.source_system_id = dv.source_system_id
          LEFT JOIN LATERAL (
            SELECT v.first_name, v.last_name, v.gender, v.race, v.age_num
              FROM cold_case.victim v
             WHERE v.case_id = cases.case_id
             ORDER BY v.victim_id ASC
             LIMIT 1
          ) AS primary_victim ON TRUE
          {where_clause}
         ORDER BY {SORT_CLAUSES[sort]}
         LIMIT :limit OFFSET :offset
    """),
            {**params, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )

    return [ColdCaseListItem(**dict(r)) for r in rows], total, total_unfiltered

"""Map endpoint queries — non-null geometry, bbox-optional, filterable.

Two query shapes share the same FROM/JOIN/WHERE/filter blocks:

- `query_cold_cases_for_map` — individual case points, capped + ordered.
  Used at high zoom where a viewport holds few enough cases to ship.
- `aggregate_cold_cases_for_map` — server-side grid clusters (centroid +
  count per `ST_SnapToGrid` cell). Used at low zoom so the browser never
  receives more than a few dozen rows regardless of corpus size.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.services.cold_cases.bbox import (
    DEFAULT_MAP_LIMIT,
    cluster_cell_degrees,
)
from casesignal.api.services.cold_cases.filters import (
    expand_gender_filter,
    expand_race_filter,
    race_exclude_filter,
)

_MAP_POINT_SELECT = """\
    SELECT
        cases.case_id,
        cases.slug,
        cases.source_case_id,
        cases.case_name,
        cases.case_type,
        cases.incident_date,
        cases.latitude,
        cases.longitude,
        cases.state,
        cases.city,
        NULLIF(
          TRIM(
            (SELECT COALESCE(v.first_name, '') || ' ' || COALESCE(v.last_name, '')
               FROM cold_case.victim v
              WHERE v.case_id = cases.case_id
              ORDER BY v.victim_id
              LIMIT 1)
          ),
          ''
        ) AS victim_primary_name,
        COALESCE(
            (SELECT ARRAY_AGG(DISTINCT v.gender ORDER BY v.gender)
               FROM cold_case.victim v
              WHERE v.case_id = cases.case_id
                AND v.gender IS NOT NULL),
            ARRAY[]::text[]
        ) AS victim_genders,
        COALESCE(
            (SELECT ARRAY_AGG(DISTINCT v.race ORDER BY v.race)
               FROM cold_case.victim v
              WHERE v.case_id = cases.case_id
                AND v.race IS NOT NULL),
            ARRAY[]::text[]
        ) AS victim_races,
        cases.geocode_precision,
        cases.source_county_fips
"""

# Cluster mode: snap each case's point to a grid and aggregate. The display
# coordinate is the mean of the member points (a real centroid), not the
# grid corner, so a sparse cell's bubble still sits on its cases.
_MAP_CLUSTER_SELECT = """\
    SELECT
        ST_SnapToGrid(cases.geom, :cell) AS cell,
        COUNT(*)              AS n,
        AVG(cases.latitude)   AS lat,
        AVG(cases.longitude)  AS lon
"""

# dv JOIN gates on ingestion_status = 'published' (SEC-2026-05-31-A): archived /
# draft / failed dataset versions are never plotted for anonymous users.
_MAP_FROM_WHERE = """\
    FROM cold_case.cases cases
    LEFT JOIN cold_case.case_extractions_current ext
              ON ext.case_id = cases.case_id AND ext.prompt_tier = 1
    JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id
              AND dv.ingestion_status = 'published'
    JOIN etl.source_system ss ON ss.source_system_id = dv.source_system_id
    WHERE cases.geom IS NOT NULL
"""

_MAP_BBOX_CLAUSE = """\
      AND cases.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)
"""

# Victim filters use an EXISTS subquery rather than a LEFT JOIN to
# cold_case.victim — a JOIN duplicates the case row for every victim,
# so multi-victim cases (e.g. Gericke 1992: 2 victims) come back as
# 2 rows pre-dedup. EXISTS keeps the result one-row-per-case while
# preserving "any victim matches" filter semantics. Same pattern as
# list_cold_cases.
_MAP_FILTERS = """\
      AND (:case_type     IS NULL OR cases.case_type = ANY(:case_type))
      AND (:year_min      IS NULL OR cases.incident_date >= make_date(:year_min, 1, 1))
      AND (:year_max      IS NULL OR cases.incident_date <= make_date(:year_max, 12, 31))
      AND (:state         IS NULL OR cases.state = :state)
      AND (:city          IS NULL OR cases.city = :city)
      AND (
        (:gender IS NULL AND :race IS NULL AND :race_other_exclude IS NULL
         AND :age_min IS NULL AND :age_max IS NULL)
        OR EXISTS (
          SELECT 1 FROM cold_case.victim v
           WHERE v.case_id = cases.case_id
             AND (:gender  IS NULL OR v.gender  = ANY(:gender))
             AND (
               (:race IS NULL AND :race_other_exclude IS NULL)
               OR (:race IS NOT NULL AND LOWER(v.race) = ANY(:race))
               OR (:race_other_exclude IS NOT NULL
                   AND v.race IS NOT NULL
                   AND LOWER(v.race) <> ALL(:race_other_exclude))
             )
             AND (:age_min IS NULL OR v.age_num >= :age_min)
             AND (:age_max IS NULL OR v.age_num <= :age_max)
        )
      )
      AND (:weapon        IS NULL OR ext.weapon = ANY(:weapon))
      AND (:location_type IS NULL OR ext.location_type = ANY(:location_type))
      AND (:source_codes  IS NULL OR ss.source_code = ANY(:source_codes))
      AND (:precision     IS NULL OR cases.geocode_precision = ANY(:precision))
"""

_MAP_POINT_TAIL = """\
    ORDER BY cases.case_id
    LIMIT :row_cap
"""

_MAP_CLUSTER_TAIL = """\
    GROUP BY ST_SnapToGrid(cases.geom, :cell)
"""

# Public geocoded-corpus size: gated to published versions (SEC-2026-05-31-A).
_TOTAL_GEOCODED_SQL = (
    "SELECT COUNT(*) FROM cold_case.cases AS cases"
    " JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id"
    " AND dv.ingestion_status = 'published'"
    " WHERE cases.geom IS NOT NULL"
)


def _filter_params(
    *,
    case_type: list[str] | None,
    year_min: int | None,
    year_max: int | None,
    state: str | None,
    city: str | None,
    gender: list[str] | None,
    race: list[str] | None,
    age_min: int | None,
    age_max: int | None,
    weapon: list[str] | None,
    location_type: list[str] | None,
    source_system: list[str] | None,
    precision: list[str] | None,
) -> dict[str, Any]:
    """Bind params for the shared `_MAP_FILTERS` block. Gender and race are both
    expanded to all stored source forms — same normalization as `list_cold_cases`,
    so map filters work regardless of client casing and a canonical race bucket
    matches every raw spelling that folds into it."""
    return {
        "case_type": case_type,
        "year_min": year_min,
        "year_max": year_max,
        "state": state,
        "city": city,
        "gender": expand_gender_filter(gender),
        "race": expand_race_filter(race),
        "race_other_exclude": race_exclude_filter(race),
        "age_min": age_min,
        "age_max": age_max,
        "weapon": weapon,
        "location_type": location_type,
        "source_codes": source_system,
        "precision": precision,
    }


def query_cold_cases_for_map(
    session: Session,
    bbox: tuple[float, float, float, float] | None,
    *,
    case_type: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    state: str | None = None,
    city: str | None = None,
    gender: list[str] | None = None,
    race: list[str] | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    weapon: list[str] | None = None,
    location_type: list[str] | None = None,
    source_system: list[str] | None = None,
    precision: list[str] | None = None,
    limit: int = DEFAULT_MAP_LIMIT,
) -> tuple[list[dict[str, Any]], bool, int]:
    """Return (rows, truncated, total_unfiltered) — individual case points.

    `truncated` is True iff the query hit the limit + 1 sentinel — i.e. there
    was at least one more row the client would have received under a higher
    limit. `total_unfiltered` is the global COUNT(*) of geocoded cases,
    ignoring filters. When `bbox` is None no geographic filter is applied.
    """
    params = _filter_params(
        case_type=case_type,
        year_min=year_min,
        year_max=year_max,
        state=state,
        city=city,
        gender=gender,
        race=race,
        age_min=age_min,
        age_max=age_max,
        weapon=weapon,
        location_type=location_type,
        source_system=source_system,
        precision=precision,
    )
    params["row_cap"] = limit + 1  # text() can't do inline arithmetic on params.

    sql_str = _MAP_POINT_SELECT + _MAP_FROM_WHERE
    if bbox is not None:
        west, south, east, north = bbox
        sql_str += _MAP_BBOX_CLAUSE
        params["west"] = west
        params["south"] = south
        params["east"] = east
        params["north"] = north
    sql_str += _MAP_FILTERS + _MAP_POINT_TAIL

    rows = session.execute(text(sql_str), params).mappings().all()

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    total_unfiltered = session.execute(text(_TOTAL_GEOCODED_SQL)).scalar() or 0

    return [dict(r) for r in rows], truncated, total_unfiltered


def aggregate_cold_cases_for_map(
    session: Session,
    bbox: tuple[float, float, float, float] | None,
    *,
    zoom: int,
    case_type: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    state: str | None = None,
    city: str | None = None,
    gender: list[str] | None = None,
    race: list[str] | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    weapon: list[str] | None = None,
    location_type: list[str] | None = None,
    source_system: list[str] | None = None,
    precision: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return (clusters, total_unfiltered) — grid-aggregated map clusters.

    Each cluster is {latitude, longitude, count}: the mean coordinate of the
    cases snapped into one `ST_SnapToGrid` cell, plus how many fell in it.
    Cell size scales with `zoom`. The result set is bounded by viewport area
    / cell area — a few dozen rows — independent of corpus size.
    """
    params = _filter_params(
        case_type=case_type,
        year_min=year_min,
        year_max=year_max,
        state=state,
        city=city,
        gender=gender,
        race=race,
        age_min=age_min,
        age_max=age_max,
        weapon=weapon,
        location_type=location_type,
        source_system=source_system,
        precision=precision,
    )
    params["cell"] = cluster_cell_degrees(zoom)

    sql_str = _MAP_CLUSTER_SELECT + _MAP_FROM_WHERE
    if bbox is not None:
        west, south, east, north = bbox
        sql_str += _MAP_BBOX_CLAUSE
        params["west"] = west
        params["south"] = south
        params["east"] = east
        params["north"] = north
    sql_str += _MAP_FILTERS + _MAP_CLUSTER_TAIL

    rows = session.execute(text(sql_str), params).mappings().all()
    clusters = [
        {
            "latitude": float(r["lat"]),
            "longitude": float(r["lon"]),
            "count": int(r["n"]),
        }
        for r in rows
    ]

    total_unfiltered = session.execute(text(_TOTAL_GEOCODED_SQL)).scalar() or 0

    return clusters, total_unfiltered

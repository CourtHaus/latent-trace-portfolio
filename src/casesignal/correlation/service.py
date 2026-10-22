"""find_correlated_cases — single entry point for the C2 correlation engine.

Two-phase: SQL pulls a geo+time-filtered candidate pool with all raw values
needed for scoring; Python runs the rarity-weighted score_pair + proximity
discount through scoring.py, applies the floor and min-dimension rules,
sorts (score DESC, distance_miles ASC), takes top-N, and shapes the response.

Race is canonicalized inside score_pair (normalization.canonical_race) so
callers never forget; weight table keys are canonical buckets.

Forward-compat: this function-shaped interface stays separate from
get_cold_case_by_id so a future caller can promote correlations to a
dedicated /cold-cases/{id}/correlations endpoint without re-architecture.
Embedding into the detail handler is right at current scale (sub-50ms on
~525 cases); embedding becomes wrong if the candidate pool grows by
orders of magnitude.

Candidate-pool exclusions: cases with NULL incident_date OR NULL geom are
filtered out at the SQL layer. year and distance_miles on
CorrelatedCaseSummary are therefore always populated. If parent case has
NULL geom or incident_date, this function returns an empty list — the
detail-page banner does not currently distinguish this from a true
no-match result; revisit in v2 if multi-state data quality makes this
common.

LATERAL victim subquery is per-row; fine at current scale (microseconds
total on ~525 cases), worth re-evaluating if correlation moves to a
separate endpoint with much larger candidate cardinality.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.correlation.base_rates import get_base_rates
from casesignal.correlation.config import (
    CORRELATION_GEO_MILES,
    CORRELATION_MIN_DIMENSIONS,
    CORRELATION_SCORE_FLOOR,
    CORRELATION_SCORE_SCALE,
    CORRELATION_TIME_YEARS,
    CORRELATION_TOP_N,
)
from casesignal.correlation.schemas import (
    CandidatePoint,
    CorrelatedCaseSummary,
    CorrelationCandidatesResponse,
)
from casesignal.correlation.scoring import DimensionValues, normalized_score, score_pair

_MILES_TO_METERS = 1609.344


_QUERY = text("""
    WITH parent AS (
        SELECT
            c.case_id, c.geom, c.incident_date,
            ext.weapon, ext.weapon_low_confidence,
            ext.location_type, ext.location_type_low_confidence,
            v.first_name, v.last_name, v.gender, v.race, v.age_num
          FROM cold_case.cases c
          JOIN etl.dataset_version dv
                    ON dv.dataset_version_id = c.dataset_version_id
                   AND dv.ingestion_status = 'published'
          LEFT JOIN cold_case.case_extractions_current ext
                    ON ext.case_id = c.case_id AND ext.prompt_tier = 1
          LEFT JOIN LATERAL (
              SELECT first_name, last_name, gender, race, age_num
              FROM cold_case.victim
              WHERE case_id = c.case_id
              ORDER BY victim_id ASC
              LIMIT 1
          ) v ON true
         WHERE c.case_id = :case_id
    ), candidates AS (
        SELECT
            c.case_id, c.slug, c.city, c.state,
            EXTRACT(YEAR FROM c.incident_date)::int AS year,
            ext.weapon, ext.weapon_low_confidence,
            ext.location_type, ext.location_type_low_confidence,
            v.first_name, v.last_name, v.gender, v.race, v.age_num,
            ST_Distance(c.geom::geography, p.geom::geography) / 1609.344 AS distance_miles,
            ABS(ROUND(
                EXTRACT(EPOCH FROM AGE(c.incident_date, p.incident_date))
                / (365.25 * 86400)
            )::int) AS years_apart
          FROM cold_case.cases c
          -- Candidates are public-facing "possibly related" rows on a detail
          -- page; gate to published versions so an archived case never surfaces
          -- as a correlation (SEC-2026-05-31-A).
          JOIN etl.dataset_version dv
                    ON dv.dataset_version_id = c.dataset_version_id
                   AND dv.ingestion_status = 'published'
          LEFT JOIN cold_case.case_extractions_current ext
                    ON ext.case_id = c.case_id AND ext.prompt_tier = 1
          LEFT JOIN LATERAL (
              SELECT first_name, last_name, gender, race, age_num
              FROM cold_case.victim
              WHERE case_id = c.case_id
              ORDER BY victim_id ASC
              LIMIT 1
          ) v ON true
          CROSS JOIN parent p
         WHERE c.case_id != p.case_id
           AND c.geom IS NOT NULL
           AND c.incident_date IS NOT NULL
           -- Bbox prefilter on the geometry GiST index (cases_geom_idx): the
           -- `&&` operator is index-backed, cutting 6.7k geocoded cases down to
           -- the local handful before the exact (but index-less, because of the
           -- ::geography cast) ST_DWithin distance check. :bbox_deg generously
           -- over-approximates the radius in degrees so it never drops a true
           -- match; ST_DWithin makes the precise cut.
           AND c.geom && ST_Expand(p.geom, :bbox_deg)
           AND ST_DWithin(c.geom::geography, p.geom::geography, :geo_meters)
           AND c.incident_date BETWEEN
                 p.incident_date - make_interval(years => :time_years)
             AND p.incident_date + make_interval(years => :time_years)
    )
    SELECT
        c.*,
        p.weapon AS p_weapon,
        p.weapon_low_confidence AS p_weapon_low_confidence,
        p.location_type AS p_location_type,
        p.location_type_low_confidence AS p_location_type_low_confidence,
        p.gender AS p_gender,
        p.race AS p_race,
        p.age_num AS p_age_num
      FROM candidates c
      CROSS JOIN parent p
""")


def _victim_primary_name(first: str | None, last: str | None) -> str | None:
    """Match the existing list-endpoint convention: NULLIF(TRIM(...), '')."""
    raw = f"{first or ''} {last or ''}".strip()
    return raw if raw else None


def _score_all_candidates(session: Session, case_id: int) -> list[CorrelatedCaseSummary]:
    """Score the full geo+time-filtered candidate pool for case_id.

    Returns ALL candidates (no floor filter), sorted (score DESC,
    distance_miles ASC). Self-excluded. Empty list when the parent has
    NULL geom / incident_date.
    """
    rows = (
        session.execute(
            _QUERY,
            {
                "case_id": case_id,
                "geo_meters": CORRELATION_GEO_MILES * _MILES_TO_METERS,
                # Radius in degrees for the bbox prefilter. 69 km/deg is below
                # the tightest CONUS degree (lon at ~49°N ≈ 73 km), so dividing
                # by it over-estimates the span — a safe superset for the index
                # scan that ST_DWithin then trims exactly.
                "bbox_deg": (CORRELATION_GEO_MILES * _MILES_TO_METERS) / 69_000.0,
                "time_years": CORRELATION_TIME_YEARS,
            },
        )
        .mappings()
        .all()
    )

    rates = get_base_rates(session)
    scored: list[CorrelatedCaseSummary] = []
    for r in rows:
        parent = DimensionValues(
            weapon=r["p_weapon"],
            weapon_low_confidence=r["p_weapon_low_confidence"],
            location_type=r["p_location_type"],
            location_type_low_confidence=r["p_location_type_low_confidence"],
            gender=r["p_gender"],
            race=r["p_race"],
            age=r["p_age_num"],
        )
        cand = DimensionValues(
            weapon=r["weapon"],
            weapon_low_confidence=r["weapon_low_confidence"],
            location_type=r["location_type"],
            location_type_low_confidence=r["location_type_low_confidence"],
            gender=r["gender"],
            race=r["race"],
            age=r["age_num"],
        )
        raw_bits, dims = score_pair(parent, cand, rates)
        distance = float(r["distance_miles"])
        score, prox = normalized_score(raw_bits, distance, r["years_apart"], rates)

        scored.append(
            CorrelatedCaseSummary(
                case_id=r["case_id"],
                slug=r["slug"],
                victim_primary_name=_victim_primary_name(r["first_name"], r["last_name"]),
                city=r["city"],
                state=r["state"],
                year=r["year"],
                score=score,
                score_max=CORRELATION_SCORE_SCALE,
                proximity_factor=prox,
                matched_dimensions=dims,
                distance_miles=distance,
                years_apart=r["years_apart"],
            )
        )

    scored.sort(key=lambda s: (-s.score, s.distance_miles))
    return scored


def find_correlated_cases(session: Session, case_id: int) -> list[CorrelatedCaseSummary]:
    """Up to CORRELATION_TOP_N leads: score >= CORRELATION_SCORE_FLOOR AND at
    least CORRELATION_MIN_DIMENSIONS matched dimensions, sorted (score DESC,
    distance ASC). Rarity-weighted; race canonicalized inside score_pair."""
    scored = _score_all_candidates(session, case_id)
    leads = [
        c
        for c in scored
        if c.score >= CORRELATION_SCORE_FLOOR
        and len(c.matched_dimensions) >= CORRELATION_MIN_DIMENSIONS
    ][:CORRELATION_TOP_N]
    return leads


_PARENT_EXISTS_QUERY = text("""
    SELECT 1
      FROM cold_case.cases c
      JOIN etl.dataset_version dv
                ON dv.dataset_version_id = c.dataset_version_id
               AND dv.ingestion_status = 'published'
     WHERE c.case_id = :case_id
     LIMIT 1
""")


def _focal_case_is_published(session: Session, case_id: int) -> bool:
    """True if case_id exists in a published dataset version.

    Lets the candidates endpoint 404 a missing/unpublished focal case (like the
    detail route) while still returning 200 + empty pool for a valid case that
    simply has no geo-temporal neighbours (or NULL geom/incident_date).
    """
    return session.execute(_PARENT_EXISTS_QUERY, {"case_id": case_id}).first() is not None


def get_correlation_candidates(
    session: Session, case_id: int
) -> CorrelationCandidatesResponse | None:
    """Full scored pool (the scatter) + the top-N floor-passing leads.

    Returns None when the focal case does not exist or is not in a published
    dataset (the route turns this into a 404), distinguishing invalid input from
    a valid focal case with an empty candidate pool.
    """
    if not _focal_case_is_published(session, case_id):
        return None
    scored = _score_all_candidates(session, case_id)
    candidates = [
        CandidatePoint(distance_miles=c.distance_miles, years_apart=c.years_apart, score=c.score)
        for c in scored
    ]
    leads = [
        c
        for c in scored
        if c.score >= CORRELATION_SCORE_FLOOR
        and len(c.matched_dimensions) >= CORRELATION_MIN_DIMENSIONS
    ][:CORRELATION_TOP_N]
    return CorrelationCandidatesResponse(
        score_max=CORRELATION_SCORE_SCALE,
        score_floor=CORRELATION_SCORE_FLOOR,
        candidates=candidates,
        leads=leads,
    )

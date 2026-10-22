"""Pydantic schemas for the C2 correlation API response."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MatchedDimension(BaseModel):
    """One contributing dimension from the score breakdown.

    name is the internal field key; value is the matched literal (e.g.,
    "firearm" for weapon, "F" for victim_gender, "34 & 36" for
    victim_age). weight is the value-dependent surprisal contribution in
    bits — rarer shared values carry higher weight. low_confidence is True
    if EITHER side's classification was low_conf — the panel renders this
    as "uncertain" appended to the value. low_confidence is always False
    for demographic dimensions (gender, race, age): demographics are
    primary data with no low_conf concept. UI MUST NOT render "uncertain"
    on demographic dimensions even if a future bug sets the flag.
    """

    name: str
    value: str
    low_confidence: bool
    weight: float

    model_config = ConfigDict(extra="forbid")


class CorrelatedCaseSummary(BaseModel):
    """One panel item. Returned in (score DESC, distance_miles ASC) order.

    Leads must clear CORRELATION_SCORE_FLOOR (0-10 scale) AND have at
    least CORRELATION_MIN_DIMENSIONS matched dimensions; zero-dim items
    score 0 and never reach the response.

    matched_dimensions is in FIXED dimension order: weapon, location_type,
    victim_gender, victim_race, victim_age (not sorted by weight; weights
    are value-dependent). Frontend renders comma-joined in this exact order.
    """

    case_id: int
    slug: str
    victim_primary_name: str | None
    city: str | None
    state: str
    year: int
    score: float
    score_max: float
    proximity_factor: float
    matched_dimensions: list[MatchedDimension]
    distance_miles: float
    years_apart: int

    model_config = ConfigDict(extra="forbid")


class CandidatePoint(BaseModel):
    """One point in the joint-distribution scatter. PII-free: coordinates + score
    only (no victim identity), since the full pool can be large."""

    distance_miles: float
    years_apart: int
    score: float

    model_config = ConfigDict(extra="forbid")


class CorrelationCandidatesResponse(BaseModel):
    """Full scored candidate pool for one focal case (the scatter) plus the
    top-N floor-passing leads (reuses CorrelatedCaseSummary)."""

    score_max: float
    score_floor: float
    candidates: list[CandidatePoint]
    leads: list[CorrelatedCaseSummary]

    model_config = ConfigDict(extra="forbid")

"""Pure scoring core for the rarity-weighted correlation engine.

No DB access. service.py feeds candidate rows + BaseRates through these
functions. Spec: docs/engineering-decisions.md.

Score model:
  raw_bits  = sum of per-dimension surprisal contributions
  proximity = 2**(-miles/D_HALF) * 2**(-years/T_HALF)
  score     = SCALE * raw_bits * proximity / raw_max(rates)
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from casesignal.correlation.base_rates import BaseRates
from casesignal.correlation.config import (
    CORRELATION_AGE_KERNEL_FULL_YEARS,
    CORRELATION_AGE_KERNEL_ZERO_YEARS,
    CORRELATION_DISTANCE_HALF_LIFE_MILES,
    CORRELATION_SCORE_SCALE,
    CORRELATION_TIME_HALF_LIFE_YEARS,
)
from casesignal.correlation.schemas import MatchedDimension
from casesignal.normalization import canonical_race


def _is_missing(value: str | None) -> bool:
    """'unknown' (any case) and NULL are absences, never matchable values."""
    return value is None or value.strip().lower() == "unknown"


def categorical_match(
    parent_val: str | None,
    parent_low: bool | None,
    cand_val: str | None,
    cand_low: bool | None,
    name: str,
    weights: Mapping[str, float],
) -> tuple[float, MatchedDimension | None]:
    """Surprisal contribution for one categorical dimension.

    Both sides must be known AND equal; the contribution is the corpus
    surprisal of the shared value. A value absent from the weight table
    (possible briefly under the TTL cache when a brand-new category appears)
    contributes nothing rather than guessing a weight.
    """
    if _is_missing(parent_val) or _is_missing(cand_val):
        return 0.0, None
    if parent_val != cand_val:
        return 0.0, None
    assert parent_val is not None  # narrowed by _is_missing above
    weight = weights.get(parent_val)
    if not weight:  # None or 0.0: absent value, or zero-information dimension
        return 0.0, None
    return weight, MatchedDimension(
        name=name,
        value=parent_val,
        low_confidence=bool(parent_low) or bool(cand_low),
        weight=weight,
    )


def age_kernel(delta_years: int) -> float:
    """1.0 within FULL years, linear taper to 0.0 at ZERO years."""
    full = CORRELATION_AGE_KERNEL_FULL_YEARS
    zero = CORRELATION_AGE_KERNEL_ZERO_YEARS
    if delta_years <= full:
        return 1.0
    if delta_years >= zero:
        return 0.0
    return (zero - delta_years) / (zero - full)


def age_match(
    parent_age: int | None,
    cand_age: int | None,
    rates: BaseRates,
) -> tuple[float, MatchedDimension | None]:
    """Graded age similarity: kernel(|delta|) * corpus age-closeness weight."""
    if parent_age is None or cand_age is None:
        return 0.0, None
    kernel = age_kernel(abs(parent_age - cand_age))
    if kernel <= 0.0 or rates.age_close_weight <= 0.0:
        return 0.0, None
    weight = kernel * rates.age_close_weight
    value = (
        str(parent_age)
        if parent_age == cand_age
        else f"{parent_age} & {cand_age}"
    )
    return weight, MatchedDimension(
        name="victim_age", value=value, low_confidence=False, weight=weight
    )


def proximity_factor(distance_miles: float, years_apart: int) -> float:
    """Multiplicative discount: half weight per D_HALF miles and per T_HALF
    years. Inputs clamped at zero: a negative would amplify instead of
    discount, and this function cannot know its caller sanitized."""
    miles = max(0.0, distance_miles)
    years = max(0, years_apart)
    geo = math.pow(2.0, -(miles / CORRELATION_DISTANCE_HALF_LIFE_MILES))
    time_ = math.pow(2.0, -(years / CORRELATION_TIME_HALF_LIFE_YEARS))
    return geo * time_


def raw_max(rates: BaseRates) -> float:
    """Deterministic best attainable raw sum: the rarest (heaviest) value per
    categorical dimension plus the full age weight. 10/10 therefore means
    'the rarest possible shared profile at zero distance and zero years'."""
    categorical = sum(
        (max(weights.values(), default=0.0) for weights in (
            rates.weapon,
            rates.location_type,
            rates.victim_gender,
            rates.victim_race,
        )),
        0.0,
    )
    return categorical + rates.age_close_weight


def normalized_score(
    raw_bits: float,
    distance_miles: float,
    years_apart: int,
    rates: BaseRates,
) -> tuple[float, float]:
    """(0-10 score, proximity factor). Proximity discounts evidence; with no
    evidence the score is zero regardless of proximity."""
    prox = proximity_factor(distance_miles, years_apart)
    rmax = raw_max(rates)
    if rmax <= 0.0 or raw_bits <= 0.0:
        return 0.0, prox
    return CORRELATION_SCORE_SCALE * raw_bits * prox / rmax, prox


@dataclass(frozen=True)
class DimensionValues:
    """One side of a pair comparison. ``race`` is the RAW source value;
    score_pair canonicalizes internally so callers cannot forget."""

    weapon: str | None = None
    weapon_low_confidence: bool | None = None
    location_type: str | None = None
    location_type_low_confidence: bool | None = None
    gender: str | None = None
    race: str | None = None
    age: int | None = None


def score_pair(
    parent: DimensionValues,
    cand: DimensionValues,
    rates: BaseRates,
) -> tuple[float, list[MatchedDimension]]:
    """Sum the per-dimension surprisal contributions for one case pair.

    The dimension set here MUST mirror raw_max's: a dimension added to one
    but not the other silently breaks the 10-point ceiling. Race is
    canonicalized on both sides before matching (canonical buckets key the
    weight table; see BaseRates docstring).
    """
    dims: list[MatchedDimension] = []
    raw_bits = 0.0

    for p_val, p_low, c_val, c_low, name, weights in (
        (parent.weapon, parent.weapon_low_confidence, cand.weapon, cand.weapon_low_confidence, "weapon", rates.weapon),
        (parent.location_type, parent.location_type_low_confidence, cand.location_type, cand.location_type_low_confidence, "location_type", rates.location_type),
        (parent.gender, None, cand.gender, None, "victim_gender", rates.victim_gender),
    ):
        s, d = categorical_match(p_val, p_low, c_val, c_low, name, weights)
        raw_bits += s
        if d is not None:
            dims.append(d)

    p_race = canonical_race(parent.race) if parent.race is not None else None
    c_race = canonical_race(cand.race) if cand.race is not None else None
    s, d = categorical_match(p_race, None, c_race, None, "victim_race", rates.victim_race)
    raw_bits += s
    if d is not None:
        dims.append(d)

    s, d = age_match(parent.age, cand.age, rates)
    raw_bits += s
    if d is not None:
        dims.append(d)

    return raw_bits, dims

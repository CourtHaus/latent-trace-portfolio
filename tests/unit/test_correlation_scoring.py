"""Pure scoring core: kernels, matches, normalization, min-evidence."""

from __future__ import annotations

import math

import pytest

from casesignal.correlation.base_rates import BaseRates
from casesignal.correlation.config import (
    CORRELATION_AGE_KERNEL_FULL_YEARS,
    CORRELATION_AGE_KERNEL_ZERO_YEARS,
    CORRELATION_DISTANCE_HALF_LIFE_MILES,
    CORRELATION_SCORE_SCALE,
    CORRELATION_TIME_HALF_LIFE_YEARS,
)
from casesignal.correlation.scoring import (
    DimensionValues,
    age_kernel,
    age_match,
    categorical_match,
    normalized_score,
    proximity_factor,
    raw_max,
    score_pair,
)

RATES = BaseRates(
    weapon={"firearm": 0.4, "asphyxiation": 4.6},
    location_type={"public_outdoor": 1.0, "residence": 1.7},
    victim_gender={"M": 0.4, "F": 2.1},
    victim_race={"White": 1.5, "Black or African American": 1.4},
    age_close_weight=3.0,
)


# --- categorical matches -------------------------------------------------

def test_match_on_rare_value_outweighs_common() -> None:
    rare, dim_rare = categorical_match("asphyxiation", False, "asphyxiation", False, "weapon", RATES.weapon)
    common, dim_common = categorical_match("firearm", False, "firearm", False, "weapon", RATES.weapon)
    assert rare > common > 0
    assert dim_rare is not None and math.isclose(dim_rare.weight, 4.6)
    assert dim_common is not None and dim_common.value == "firearm"


def test_no_match_on_difference_or_missing() -> None:
    assert categorical_match("firearm", False, "knife", False, "weapon", RATES.weapon) == (0.0, None)
    assert categorical_match(None, None, "firearm", False, "weapon", RATES.weapon) == (0.0, None)


def test_unknown_is_missing_not_a_match() -> None:
    assert categorical_match("unknown", False, "unknown", False, "weapon", RATES.weapon) == (0.0, None)
    assert categorical_match("Unknown", False, "Unknown", False, "victim_gender", RATES.victim_gender) == (0.0, None)


def test_low_confidence_flag_propagates_from_either_side() -> None:
    _, dim = categorical_match("firearm", True, "firearm", False, "weapon", RATES.weapon)
    assert dim is not None and dim.low_confidence is True


def test_value_absent_from_weight_table_does_not_match() -> None:
    # e.g. a brand-new categorical value not yet in the (TTL-cached) table.
    assert categorical_match("laser", False, "laser", False, "weapon", RATES.weapon) == (0.0, None)


# --- age ------------------------------------------------------------------

def test_age_kernel_shape() -> None:
    assert age_kernel(0) == 1.0
    assert age_kernel(CORRELATION_AGE_KERNEL_FULL_YEARS) == 1.0
    assert age_kernel(CORRELATION_AGE_KERNEL_ZERO_YEARS) == 0.0
    assert age_kernel(CORRELATION_AGE_KERNEL_ZERO_YEARS + 10) == 0.0
    mid = (CORRELATION_AGE_KERNEL_FULL_YEARS + CORRELATION_AGE_KERNEL_ZERO_YEARS) // 2
    assert 0.0 < age_kernel(mid) < 1.0


def test_age_match_graded_no_decade_cliff() -> None:
    s_close, dim = age_match(39, 40, RATES)   # old band formula: no match
    s_far, _ = age_match(31, 39, RATES)       # old band formula: full match
    assert s_close > s_far                     # the cliff is gone
    assert dim is not None and dim.name == "victim_age"
    assert s_close == pytest.approx(age_kernel(1) * RATES.age_close_weight)


def test_age_match_missing_or_beyond_taper() -> None:
    assert age_match(None, 30, RATES) == (0.0, None)
    assert age_match(20, 60, RATES) == (0.0, None)


# --- proximity + normalization ---------------------------------------------

def test_proximity_factor_half_lives() -> None:
    assert proximity_factor(0.0, 0) == 1.0
    assert proximity_factor(CORRELATION_DISTANCE_HALF_LIFE_MILES, 0) == pytest.approx(0.5)
    years = 7
    assert proximity_factor(0.0, years) == pytest.approx(
        2.0 ** (-(years / CORRELATION_TIME_HALF_LIFE_YEARS))
    )
    assert proximity_factor(10.0, 5) < 1.0


def test_proximity_discounts_but_never_creates() -> None:
    score_zero, _ = normalized_score(0.0, 0.0, 0, RATES)
    assert score_zero == 0.0


def test_normalized_score_ceiling_and_ordering() -> None:
    rmax = raw_max(RATES)
    assert rmax == pytest.approx(4.6 + 1.7 + 2.1 + 1.5 + 3.0)
    best, prox = normalized_score(rmax, 0.0, 0, RATES)
    assert best == pytest.approx(CORRELATION_SCORE_SCALE)
    assert prox == 1.0
    near, _ = normalized_score(2.0, 1.0, 0, RATES)
    far, _ = normalized_score(2.0, 45.0, 18, RATES)
    assert near > far > 0


def test_age_match_value_formats_and_confidence() -> None:
    _, dim_equal = age_match(34, 34, RATES)
    assert dim_equal is not None and dim_equal.value == "34"
    _, dim_diff = age_match(34, 36, RATES)
    assert dim_diff is not None and dim_diff.value == "34 & 36"
    assert dim_diff.low_confidence is False


def test_normalized_score_monotone_in_raw_bits() -> None:
    lo, _ = normalized_score(1.0, 5.0, 2, RATES)
    hi, _ = normalized_score(2.0, 5.0, 2, RATES)
    assert hi > lo


def test_proximity_factor_clamps_negative_inputs() -> None:
    assert proximity_factor(-5.0, -3) == 1.0


def test_score_pair_canonicalizes_race_and_mirrors_raw_max_dimensions() -> None:
    parent = DimensionValues(
        weapon="asphyxiation", weapon_low_confidence=False,
        location_type="residence", location_type_low_confidence=False,
        gender="F", race="black", age=34,
    )
    cand = DimensionValues(
        weapon="asphyxiation", weapon_low_confidence=False,
        location_type="residence", location_type_low_confidence=False,
        gender="F", race="BLACK or AFRICAN AMERICAN", age=35,
    )
    raw_bits, dims = score_pair(parent, cand, RATES)
    names = [d.name for d in dims]
    assert names == ["weapon", "location_type", "victim_gender", "victim_race", "victim_age"]
    # Cross-spelling race match worked via canonicalization:
    race_dim = next(d for d in dims if d.name == "victim_race")
    assert race_dim.value == "Black or African American"
    # All five dimensions matched at near-best values: raw_bits approaches raw_max.
    assert raw_bits == pytest.approx(4.6 + 1.7 + 2.1 + 1.4 + 3.0)
    assert raw_bits <= raw_max(RATES)


def test_score_pair_empty_sides() -> None:
    raw_bits, dims = score_pair(DimensionValues(), DimensionValues(), RATES)
    assert raw_bits == 0.0
    assert dims == []

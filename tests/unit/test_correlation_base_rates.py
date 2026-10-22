"""Pure math for rarity weights: smoothing, surprisal, age closeness."""

from __future__ import annotations

import math

from casesignal.correlation.base_rates import (
    age_close_weight,
    surprisal_weights,
)


def test_surprisal_weights_rarer_is_heavier() -> None:
    w = surprisal_weights({"firearm": 75, "knife": 20, "asphyxiation": 5})
    assert w["asphyxiation"] > w["knife"] > w["firearm"] > 0


def test_surprisal_weights_exact_value_with_alpha_one() -> None:
    # P(a) = (9+1)/(10+1*2) = 10/12; w = -log2(10/12)
    w = surprisal_weights({"a": 9, "b": 1})
    assert math.isclose(w["a"], -math.log2(10 / 12))
    assert math.isclose(w["b"], -math.log2(2 / 12))


def test_surprisal_weights_empty_and_zero_counts() -> None:
    assert surprisal_weights({}) == {}
    assert "z" not in surprisal_weights({"a": 3, "z": 0})


def test_age_close_weight_uniform_histogram() -> None:
    # 100 victims uniform on 0..99: expected = -log2(P(|A-B|<=5)) computed
    # exactly by pair counting.
    hist = {a: 1 for a in range(100)}
    w = age_close_weight(hist, close_years=5)
    pairs_close = sum(
        sum(1 for b in range(100) if abs(a - b) <= 5) for a in range(100)
    )
    expected = -math.log2(pairs_close / (100 * 100))
    assert math.isclose(w, expected)
    assert w > 0


def test_age_close_weight_concentrated_histogram_is_light() -> None:
    # Everyone is 30: ages always within 5 by chance — zero surprise.
    assert age_close_weight({30: 50}, close_years=5) == 0.0


def test_age_close_weight_degenerate() -> None:
    assert age_close_weight({}, close_years=5) == 0.0
    assert age_close_weight({40: 1}, close_years=5) == 0.0

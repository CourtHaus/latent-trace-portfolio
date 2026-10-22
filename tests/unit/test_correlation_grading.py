"""Unit tests for the pure helpers in tools.correlation_grading.

These cover the DB-free helpers only: concordance (Mann-Whitney/AUC),
lead_volume_curve (NEW-rule pair count per floor), and stratify (the
deterministic stratified sample). The full pipeline is smoke-tested
separately against the local live DB.
"""

from __future__ import annotations

import pytest

from tools.correlation_grading import concordance, lead_volume_curve, stratify


def test_concordance_orders_perfect_separation() -> None:
    assert concordance([5.0, 6.0], [1.0, 2.0]) == 1.0


def test_concordance_random_is_half() -> None:
    assert concordance([1.0, 2.0], [1.0, 2.0]) == pytest.approx(0.5)


def test_concordance_inverted_is_zero() -> None:
    assert concordance([1.0], [5.0]) == 0.0


def test_concordance_empty_side_returns_half() -> None:
    assert concordance([], [1.0]) == 0.5
    assert concordance([1.0], []) == 0.5


def _pair(
    parent_id: int,
    cand_id: int,
    *,
    new_score: float,
    new_dims: int,
    old_score: float = 0.0,
) -> dict[str, object]:
    """Minimal pair dict for the curve/stratify helpers (see their docstrings)."""
    return {
        "parent_id": parent_id,
        "cand_id": cand_id,
        "new_score": new_score,
        "new_dims": ["weapon"] * new_dims,
        "old_score": old_score,
        "old_dims": [],
        "distance_miles": float(cand_id),
    }


def test_lead_volume_curve_is_monotone_non_increasing() -> None:
    pairs = [
        _pair(1, 10, new_score=0.5, new_dims=2),
        _pair(1, 11, new_score=1.5, new_dims=2),
        _pair(1, 12, new_score=3.0, new_dims=2),
        _pair(2, 20, new_score=2.0, new_dims=2),
        _pair(2, 21, new_score=4.5, new_dims=1),  # fails min-dims, never a lead
    ]
    floors = [0.25 * i for i in range(1, 21)]  # 0.25 .. 5.0
    curve = lead_volume_curve(pairs, floors)
    counts = [c for _, c in curve]
    # Non-increasing as the floor rises.
    assert all(a >= b for a, b in zip(counts, counts[1:], strict=False))
    # Floors align with the requested list.
    assert [f for f, _ in curve] == floors


def test_lead_volume_curve_hand_counted() -> None:
    pairs = [
        _pair(1, 10, new_score=0.5, new_dims=2),  # below 1.0
        _pair(1, 11, new_score=1.5, new_dims=2),  # >= 1.0, ok dims
        _pair(1, 12, new_score=3.0, new_dims=2),  # >= 1.0, ok dims
        _pair(2, 20, new_score=2.0, new_dims=2),  # >= 1.0, ok dims
        _pair(2, 21, new_score=4.5, new_dims=1),  # fails min-dims
    ]
    # At floor 1.0: pairs (1,11),(1,12),(2,20) qualify -> 3.
    assert dict(lead_volume_curve(pairs, [1.0]))[1.0] == 3
    # At floor 2.5: only (1,12)=3.0 -> 1.
    assert dict(lead_volume_curve(pairs, [2.5]))[2.5] == 1
    # At floor 5.0: none.
    assert dict(lead_volume_curve(pairs, [5.0]))[5.0] == 0


def test_lead_volume_curve_top_n_caps_per_parent() -> None:
    # One parent with 8 qualifying candidates; top-N (5) caps the count.
    pairs = [
        _pair(1, 10 + i, new_score=2.0 + i, new_dims=2) for i in range(8)
    ]
    assert dict(lead_volume_curve(pairs, [1.0]))[1.0] == 5


def _strat_pair(
    parent_id: int,
    cand_id: int,
    *,
    old_lead: bool,
    new_lead: bool,
    new_score: float,
) -> dict[str, object]:
    old_score = 2.0 if old_lead else 0.0
    new_dims = 2 if new_lead else (1 if new_score >= 1.0 else 0)
    return {
        "parent_id": parent_id,
        "cand_id": cand_id,
        "new_score": new_score,
        "new_dims": ["weapon", "victim_gender"][:new_dims],
        "old_score": old_score,
        "old_dims": ["weapon", "location_type"] if old_lead else [],
        "distance_miles": float(cand_id),
    }


def test_stratify_is_deterministic_and_covers_strata() -> None:
    pairs: list[dict[str, object]] = []
    # Stratum: old-only leads (old lead, not new lead).
    for i in range(10):
        pairs.append(
            _strat_pair(1, 100 + i, old_lead=True, new_lead=False, new_score=0.4)
        )
    # Stratum: new-only leads.
    for i in range(10):
        pairs.append(
            _strat_pair(2, 200 + i, old_lead=False, new_lead=True, new_score=3.0)
        )
    # Stratum: both.
    for i in range(10):
        pairs.append(
            _strat_pair(3, 300 + i, old_lead=True, new_lead=True, new_score=4.0)
        )
    # Stratum: non-leads spread across new_score quartiles.
    for i in range(10):
        pairs.append(
            _strat_pair(
                4, 400 + i, old_lead=False, new_lead=False, new_score=0.1 * i
            )
        )

    first = stratify(pairs, 20)
    second = stratify(pairs, 20)

    # Determinism: identical output across runs (no RNG).
    assert first == second
    assert len(first) <= 20

    def is_old_lead(p: dict[str, object]) -> bool:
        return float(p["old_score"]) >= 1.5  # type: ignore[arg-type]

    def is_new_lead(p: dict[str, object]) -> bool:
        return float(p["new_score"]) >= 1.0 and len(p["new_dims"]) >= 2  # type: ignore[arg-type]

    old_only = [p for p in first if is_old_lead(p) and not is_new_lead(p)]
    new_only = [p for p in first if is_new_lead(p) and not is_old_lead(p)]
    both = [p for p in first if is_old_lead(p) and is_new_lead(p)]
    neither = [p for p in first if not is_old_lead(p) and not is_new_lead(p)]

    # All four strata are represented when the input supplies them.
    assert old_only
    assert new_only
    assert both
    assert neither

"""Tests for CSV-baseline drift detection."""

from __future__ import annotations


def test_within_silent_band() -> None:
    """Δ ≤ 5% → silent."""
    from casesignal.etl.adapters.cold_case_co.scrape_search import drift_check

    assert drift_check(baseline=1400, live=1400) == "silent"
    assert drift_check(baseline=1400, live=1450) == "silent"  # 3.6%
    assert drift_check(baseline=1400, live=1350) == "silent"  # 3.6%


def test_warn_band() -> None:
    """5% < Δ ≤ 20% → warn."""
    from casesignal.etl.adapters.cold_case_co.scrape_search import drift_check

    assert drift_check(baseline=1400, live=1500) == "warn"  # 7.1%
    assert drift_check(baseline=1400, live=1200) == "warn"  # 14.3%


def test_abort_band() -> None:
    """Δ > 20% → abort."""
    from casesignal.etl.adapters.cold_case_co.scrape_search import drift_check

    assert drift_check(baseline=1400, live=1700) == "abort"  # 21.4%
    assert drift_check(baseline=1400, live=1100) == "abort"  # 21.4%


def test_zero_baseline_aborts() -> None:
    """Defensive: division-by-zero guard."""
    from casesignal.etl.adapters.cold_case_co.scrape_search import drift_check

    assert drift_check(baseline=0, live=10) == "abort"

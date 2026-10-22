"""Unit tests for the pure freshness-report logic (no DB / no clock)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tools.ingestion_freshness import SourceFreshness, age_days, build_report

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)


def test_age_days_undated_is_none() -> None:
    assert age_days(None, NOW) is None


def test_age_days_counts_whole_days_and_floors_at_zero() -> None:
    assert age_days(NOW - timedelta(days=10, hours=5), NOW) == 10
    assert age_days(NOW + timedelta(days=1), NOW) == 0  # future clamps to 0


def _src(code: str, days_old: int | None, cases: int = 1) -> SourceFreshness:
    last = None if days_old is None else NOW - timedelta(days=days_old)
    return SourceFreshness(source_code=code, last_ingest=last, published_cases=cases)


def test_build_report_flags_stale_and_orders_oldest_first() -> None:
    rows = [
        _src("FRESH", 5),
        _src("STALE", 90),
        _src("NEVER", None),
    ]
    text, any_stale = build_report(rows, stale_days=60, now=NOW)

    assert any_stale is True
    # Undated first, then oldest-to-newest.
    assert text.index("NEVER") < text.index("STALE") < text.index("FRESH")
    # Threshold classification.
    fresh_line = next(ln for ln in text.splitlines() if ln.startswith("FRESH"))
    stale_line = next(ln for ln in text.splitlines() if ln.startswith("STALE"))
    assert fresh_line.endswith("ok")
    assert stale_line.endswith("STALE")
    assert "2 stale (> 60d). ACTION NEEDED" in text


def test_build_report_all_fresh() -> None:
    rows = [_src("A", 3), _src("B", 30)]
    text, any_stale = build_report(rows, stale_days=60, now=NOW)
    assert any_stale is False
    assert "0 stale" in text
    assert "all fresh" in text


def test_build_report_boundary_is_inclusive_at_threshold() -> None:
    # Exactly at the threshold is still ok; one day past is stale.
    at = build_report([_src("AT", 60)], stale_days=60, now=NOW)
    past = build_report([_src("PAST", 61)], stale_days=60, now=NOW)
    assert at[1] is False
    assert past[1] is True

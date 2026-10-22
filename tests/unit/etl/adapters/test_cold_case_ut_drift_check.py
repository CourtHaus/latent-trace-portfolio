from __future__ import annotations

from typing import Any

import pytest

from casesignal.etl.adapters.cold_case_ut.scrape_sitemap import drift_check


@pytest.mark.parametrize(
    "baseline,live,expected",
    [
        (586, 586, "silent"),
        (586, 600, "silent"),  # +2.39%  within 5%
        (586, 558, "silent"),  # -4.78%  within 5%
        (586, 650, "warn"),  # +10.92% within 5–20%
        (586, 470, "warn"),  # -19.80% within 5–20%
        (586, 800, "abort"),  # +36.52% over 20%
        (586, 400, "abort"),  # -31.74% over 20%
        (0, 100, "abort"),  # baseline=0 → abort guard
    ],
)
def test_drift_check(baseline: Any, live: Any, expected: Any) -> None:
    assert drift_check(baseline=baseline, live=live) == expected

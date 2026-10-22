"""Tests for the AR county-name → FIPS lookup."""

from __future__ import annotations

from casesignal.etl.adapters.cold_case_ar_asp.county_fips import AR_COUNTY_FIPS, lookup


def test_all_75_counties_present() -> None:
    assert len(AR_COUNTY_FIPS) == 75
    assert all(f.startswith("05") and len(f) == 5 for f in AR_COUNTY_FIPS.values())


def test_lookup_exact() -> None:
    assert lookup("Washington") == "05143"
    assert lookup("Calhoun") == "05013"
    assert lookup("St. Francis") == "05123"


def test_lookup_case_insensitive_and_county_suffix() -> None:
    assert lookup("washington") == "05143"
    assert lookup("Washington County") == "05143"
    assert lookup("PULASKI COUNTY") == "05119"


def test_lookup_unknown_and_empty() -> None:
    assert lookup("Narnia") is None
    assert lookup("") is None
    assert lookup(None) is None

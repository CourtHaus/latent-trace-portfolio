"""Tests for Colorado county-name → FIPS code lookup."""

from __future__ import annotations


def test_known_counties_resolve() -> None:
    from casesignal.etl.adapters.cold_case_co.county_fips import lookup

    assert lookup("Denver") == "08031"
    assert lookup("El Paso") == "08041"
    assert lookup("Adams") == "08001"
    assert lookup("Jefferson") == "08059"
    assert lookup("Pueblo") == "08101"


def test_case_insensitive() -> None:
    from casesignal.etl.adapters.cold_case_co.county_fips import lookup

    assert lookup("DENVER") == "08031"
    assert lookup("denver") == "08031"
    assert lookup("Denver County") == "08031"  # "X County" suffix handled


def test_unknown_returns_none() -> None:
    from casesignal.etl.adapters.cold_case_co.county_fips import lookup

    assert lookup("Bogus") is None
    assert lookup("") is None
    assert lookup(None) is None


def test_all_64_co_counties_present() -> None:
    """CO has 64 counties; the lookup table should cover all of them."""
    from casesignal.etl.adapters.cold_case_co.county_fips import _COUNTY_FIPS

    assert len(_COUNTY_FIPS) == 64
    # All FIPS values should start with "08" (Colorado state code) and be 5 chars
    assert all(v.startswith("08") and len(v) == 5 for v in _COUNTY_FIPS.values())

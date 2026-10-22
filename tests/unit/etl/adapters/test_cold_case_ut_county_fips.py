from __future__ import annotations

from casesignal.etl.adapters.cold_case_ut.county_fips import (
    COUNTY_FIPS,
    lookup,
    lookup_with_city_fallback,
)


def test_all_29_counties_present() -> None:
    assert len(COUNTY_FIPS) == 29


def test_lookup_canonical() -> None:
    assert lookup("Salt Lake") == "49035"
    assert lookup("Utah") == "49049"
    assert lookup("Kane") == "49025"
    assert lookup("Weber") == "49057"


def test_lookup_case_insensitive_and_strips_county_suffix() -> None:
    assert lookup("salt lake") == "49035"
    assert lookup("Salt Lake County") == "49035"
    assert lookup("SALT LAKE COUNTY") == "49035"


def test_lookup_unknown_returns_none() -> None:
    assert lookup("Bogus") is None
    assert lookup(None) is None
    assert lookup("") is None


def test_lookup_with_city_fallback_uses_county_when_present() -> None:
    assert lookup_with_city_fallback(city="South Salt Lake", county="Salt Lake") == "49035"


def test_lookup_with_city_fallback_falls_back_to_city() -> None:
    assert lookup_with_city_fallback(city="Salt Lake City", county=None) == "49035"
    assert lookup_with_city_fallback(city="South Salt Lake", county=None) == "49035"
    assert lookup_with_city_fallback(city="Provo", county=None) == "49049"
    assert lookup_with_city_fallback(city="West Valley City", county=None) == "49035"


def test_lookup_with_city_fallback_covers_small_cities() -> None:
    """Helper, Sunset, Roosevelt added in Phase 4.2 cleanup to recover failed-geocode cases."""
    assert lookup_with_city_fallback(city="Helper", county=None) == "49007"
    assert lookup_with_city_fallback(city="Sunset", county=None) == "49011"
    assert lookup_with_city_fallback(city="Roosevelt", county=None) == "49013"


def test_lookup_with_city_fallback_unknown_city_returns_none() -> None:
    assert lookup_with_city_fallback(city="Atlantis", county=None) is None
    assert lookup_with_city_fallback(city=None, county=None) is None

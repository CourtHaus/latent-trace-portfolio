"""OH county-FIPS lookup + city-to-county fallback."""

from __future__ import annotations

from casesignal.etl.adapters.cold_case_oh_ag.county_fips import (
    OH_COUNTY_FIPS,
)
from casesignal.etl.adapters.cold_case_oh_ag.county_fips import lookup as oh_lookup


def test_county_count_is_88() -> None:
    """Ohio has 88 counties — exact constant."""
    assert len(OH_COUNTY_FIPS) == 88


def test_canonical_county_lookup() -> None:
    assert oh_lookup("Paulding County") == "39125"
    assert oh_lookup("Hamilton County") == "39061"
    assert oh_lookup("Cuyahoga County") == "39035"
    assert oh_lookup("Franklin County") == "39049"
    assert oh_lookup("Lucas County") == "39095"


def test_county_lookup_case_insensitive() -> None:
    assert oh_lookup("hamilton county") == "39061"
    assert oh_lookup("HAMILTON COUNTY") == "39061"


def test_county_lookup_strips_county_suffix() -> None:
    """Some sources publish 'Hamilton' without 'County' suffix."""
    assert oh_lookup("Hamilton") == "39061"


def test_unknown_county_returns_none() -> None:
    assert oh_lookup("Bogus County") is None
    assert oh_lookup("") is None
    assert oh_lookup(None) is None

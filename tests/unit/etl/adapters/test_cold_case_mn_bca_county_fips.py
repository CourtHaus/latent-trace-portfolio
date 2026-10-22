"""Unit tests for the MN BCA county-FIPS lookup."""

from __future__ import annotations

from casesignal.etl.adapters.cold_case_mn_bca.county_fips import (
    MN_COUNTY_FIPS,
    lookup,
)


def test_dict_has_all_87_counties() -> None:
    assert len(MN_COUNTY_FIPS) == 87
    # Every value is a 5-digit FIPS in state 27.
    for fips in MN_COUNTY_FIPS.values():
        assert len(fips) == 5
        assert fips.startswith("27")


def test_lookup_plain_name() -> None:
    assert lookup("Hennepin") == "27053"
    assert lookup("Ramsey") == "27123"


def test_lookup_is_case_insensitive_and_tolerates_county_suffix() -> None:
    assert lookup("hennepin county") == "27053"
    assert lookup("  RAMSEY County ") == "27123"


def test_lookup_handles_st_louis_with_period() -> None:
    # The harvest spells it "St. Louis" (with a period).
    assert lookup("St. Louis") == "27137"


def test_lookup_multiword_counties() -> None:
    assert lookup("Blue Earth") == "27013"
    assert lookup("Lac qui Parle") == "27073"
    assert lookup("Le Sueur") == "27079"
    assert lookup("Otter Tail") == "27111"


def test_lookup_unknown_or_empty_returns_none() -> None:
    assert lookup(None) is None
    assert lookup("") is None
    assert lookup("Nonesuch") is None

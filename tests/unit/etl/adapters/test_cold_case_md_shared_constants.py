"""Constants test — ensures Charles + Wicomico FIPS / display labels exist."""

from casesignal.etl.adapters.cold_case_md_shared.constants import (
    MD_COUNTY_DISPLAY,
    MD_COUNTY_FIPS,
)


def test_charles_constants_present() -> None:
    assert MD_COUNTY_FIPS["charles"] == "24017"
    assert MD_COUNTY_DISPLAY["charles"] == "Charles County"


def test_wicomico_constants_present() -> None:
    assert MD_COUNTY_FIPS["wicomico"] == "24045"
    assert MD_COUNTY_DISPLAY["wicomico"] == "Wicomico County"

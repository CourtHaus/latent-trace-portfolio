# tests/unit/etl/adapters/test_cold_case_ut_transform_helpers.py
"""Unit tests for _derive_city_county_from_agency helper in UT transform."""

from typing import Any

import pytest

from casesignal.etl.adapters.cold_case_ut.transform import _derive_city_county_from_agency


@pytest.mark.parametrize(
    "agency,expected",
    [
        ("Salt Lake City PD", ("Salt Lake City", None)),
        ("Salt Lake City Police", ("Salt Lake City", None)),
        ("Salt Lake City Police Department", ("Salt Lake City", None)),
        ("Provo PD", ("Provo", None)),
        ("Ogden Police Department", ("Ogden", None)),
        ("Ogden City PD", ("Ogden", None)),  # "City" stripped (colloquial)
        ("Sandy City police", ("Sandy", None)),
        ("West Valley City PD", ("West Valley City", None)),  # preserved
        (
            "West Valley PD",
            ("West Valley", None),
        ),  # "City" not in input; city→county alias covers FIPS
        ("West Jordan City PD", ("West Jordan", None)),
        ("Brigham City PD", ("Brigham City", None)),  # preserved
        ("Cedar City PD", ("Cedar City", None)),  # preserved
        ("South Salt Lake PD", ("South Salt Lake", None)),
        (
            "South Salt Lake City PD",
            ("South Salt Lake", None),
        ),  # "City" stripped; canonical = "South Salt Lake"
        ("Kane County Sheriff Office", (None, "Kane")),
        ("Davis County Sheriff's Office", (None, "Davis")),
        ("Davis County Sheriffs Office", (None, "Davis")),
        ("Wasatch County Sheriff’s office", (None, "Wasatch")),  # curly apostrophe
        ("Salt Lake County Sheriff's Office", (None, "Salt Lake")),
        ("San Juan County Sheriff Office", (None, "San Juan")),
        ("Detective Cordon Parks with the Salt Lake City Police", ("Salt Lake City", None)),
        ("Salt Lake City PD, 2001-89798", ("Salt Lake City", None)),  # comma strip
        ("SBI", (None, None)),
        ("Salt Lake City", (None, None)),  # conservative — no PD/Sheriff
        ("", (None, None)),
        (None, (None, None)),
        (
            "Unified Police Department",
            (None, "Salt Lake"),
        ),  # special-cased; UPD is multi-jurisdiction
        ("Unified PD", (None, "Salt Lake")),  # alternate form
    ],
)
def test_derive_city_county_from_agency(agency: Any, expected: Any) -> None:
    assert _derive_city_county_from_agency(agency) == expected

from casesignal.etl.adapters.cold_case_wy_dci.county_fips import lookup


def test_known_counties() -> None:
    assert lookup("Natrona") == "56025"
    assert lookup("Sweetwater") == "56037"
    assert lookup("Albany") == "56001"


def test_case_insensitive() -> None:
    assert lookup("natrona") == "56025"
    assert lookup("SWEETWATER") == "56037"


def test_with_county_suffix() -> None:
    assert lookup("Jackson County") == "56039"
    assert lookup("Jackson") == "56039"
    assert lookup("Albany County") == "56001"


def test_unknown_returns_none() -> None:
    assert lookup("Atlantis") is None
    assert lookup("") is None
    assert lookup(None) is None


def test_all_data_counties_resolve() -> None:
    """Every county that appears in the Wyoming source data must resolve."""
    data_counties = [
        "Albany",
        "Campbell",
        "Carbon",
        "Converse",
        "Crook",
        "Fremont",
        "Jackson County",
        "Laramie",
        "Natrona",
        "Platte",
        "Sheridan",
        "Sweetwater",
    ]
    for c in data_counties:
        assert lookup(c) is not None, f"unresolved data county: {c}"

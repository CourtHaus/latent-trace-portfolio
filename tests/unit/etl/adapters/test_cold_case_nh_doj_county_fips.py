"""NH town -> county FIPS lookup tests."""

from casesignal.etl.adapters.cold_case_nh_doj.county_fips import lookup


def test_manchester_is_hillsborough() -> None:
    # Manchester is the seat of Hillsborough County (FIPS 33011).
    assert lookup("Manchester") == "33011"


def test_concord_is_merrimack() -> None:
    # Concord is the state capital, seat of Merrimack County (FIPS 33013).
    assert lookup("Concord") == "33013"


def test_hooksett_is_merrimack() -> None:
    # Hooksett is in Merrimack County (FIPS 33013).
    assert lookup("Hooksett") == "33013"


def test_portsmouth_is_rockingham() -> None:
    # Portsmouth is in Rockingham County (FIPS 33015).
    assert lookup("Portsmouth") == "33015"


def test_case_insensitive() -> None:
    assert lookup("MANCHESTER") == lookup("manchester") == lookup("Manchester")


def test_unknown_town_returns_none() -> None:
    assert lookup("XyzzyTownThatDoesNotExist") is None


def test_blank_returns_none() -> None:
    assert lookup("") is None
    assert lookup(None) is None

"""parse_bbox — turns the raw 'west,south,east,north' query param into 4 validated floats."""

from __future__ import annotations

import pytest


def test_happy_path_returns_four_floats() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    result = parse_bbox("-80.0,36.0,-75.0,40.0")
    assert result == (-80.0, 36.0, -75.0, 40.0)


def test_accepts_extra_whitespace() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    assert parse_bbox(" -80 , 36 , -75 , 40 ") == (-80.0, 36.0, -75.0, 40.0)


def test_rejects_wrong_comma_count() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    with pytest.raises(ValueError, match="exactly 4"):
        parse_bbox("1,2,3")
    with pytest.raises(ValueError, match="exactly 4"):
        parse_bbox("1,2,3,4,5")


def test_rejects_non_numeric() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    with pytest.raises(ValueError, match="numeric"):
        parse_bbox("a,b,c,d")


def test_rejects_lon_out_of_range() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    with pytest.raises(ValueError, match="longitude"):
        parse_bbox("-200,36,-75,40")
    with pytest.raises(ValueError, match="longitude"):
        parse_bbox("-80,36,200,40")


def test_rejects_lat_out_of_range() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    with pytest.raises(ValueError, match="latitude"):
        parse_bbox("-80,-95,-75,40")
    with pytest.raises(ValueError, match="latitude"):
        parse_bbox("-80,36,-75,95")


def test_rejects_degenerate_rectangle() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    with pytest.raises(ValueError, match="degenerate"):
        parse_bbox("-75,36,-75,40")  # east == west
    with pytest.raises(ValueError, match="degenerate"):
        parse_bbox("-80,40,-75,40")  # north == south


def test_rejects_east_west_inversion() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    with pytest.raises(ValueError, match="degenerate"):
        parse_bbox("-75,36,-80,40")  # east < west


def test_rejects_north_south_inversion() -> None:
    from casesignal.api.services.cold_cases import parse_bbox

    with pytest.raises(ValueError, match="degenerate"):
        parse_bbox("-80,40,-75,36")  # north < south

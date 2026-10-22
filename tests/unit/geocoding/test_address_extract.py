"""extract_address — pull a geocodable fragment from narrative prose."""

from __future__ import annotations

from typing import Any

import pytest

from casesignal.geocoding.address_extract import extract_address


def test_returns_none_for_empty_or_none() -> None:
    assert extract_address(None) is None
    assert extract_address("") is None
    assert extract_address("   ") is None


def test_block_of_pattern() -> None:
    narrative = (
        "Officers responded to the 3200 block of West Colfax Avenue at "
        "approximately 11:45 PM and located the victim."
    )
    assert extract_address(narrative) == "3200 West Colfax Avenue"


def test_block_of_pattern_md_style() -> None:
    """Real MD narrative phrasing — 'block of <street> in <town>'."""
    narrative = "The body was found in the 10100 block of Washington Boulevard in Laurel."
    # Block-of stops at the "in" clause-boundary — that's intentional;
    # caller appends locality context via the city/state args.
    assert extract_address(narrative, city="Laurel", state_code="MD") == (
        "10100 Washington Boulevard, Laurel, MD"
    )


def test_standard_street_address() -> None:
    narrative = "The victim was last seen at 3168 West 14th Avenue around midnight."
    assert extract_address(narrative) == "3168 West 14th Avenue"


def test_intersection_full_form() -> None:
    narrative = "The shooting occurred near 32nd Avenue and Vine Street in the early hours."
    assert extract_address(narrative) == "32nd Avenue and Vine Street"


def test_intersection_short_form() -> None:
    narrative = "She was last seen on Welton and Glenarm Streets that evening."
    result = extract_address(narrative)
    assert result is not None
    assert "Welton" in result and "Glenarm" in result


def test_between_pattern() -> None:
    narrative = (
        "The body was found in the alley between Welton and Glenarm Streets shortly after dawn."
    )
    result = extract_address(narrative)
    assert result is not None
    assert "Welton" in result and "Glenarm" in result


def test_no_suffix_intersection_with_trigger() -> None:
    narrative = "Witnesses placed the suspect at the intersection of 43rd and Pecos."
    assert extract_address(narrative) == "43rd and Pecos"


def test_no_suffix_intersection_without_trigger_is_skipped() -> None:
    """'X and Y' alone (no trigger word) is ambiguous prose — don't claim it."""
    narrative = "Pecos and Federal were close friends."
    assert extract_address(narrative) is None


def test_lone_street_near_landmark() -> None:
    narrative = "Detectives canvassed the area near West Yale Avenue and found nothing."
    result = extract_address(narrative)
    assert result is not None
    assert "Yale" in result


def test_city_and_state_suffixed() -> None:
    narrative = "The 3200 block of West Colfax Avenue was the scene."
    assert extract_address(narrative, city="Denver", state_code="CO") == (
        "3200 West Colfax Avenue, Denver, CO"
    )


def test_only_state_suffix() -> None:
    narrative = "Officers found the body at 3168 West 14th Avenue."
    assert extract_address(narrative, state_code="CO") == "3168 West 14th Avenue, CO"


def test_only_city_suffix() -> None:
    narrative = "The 3200 block of West Colfax Avenue was the scene."
    assert extract_address(narrative, city="Denver") == "3200 West Colfax Avenue, Denver"


def test_empty_city_or_state_dropped() -> None:
    """Empty / whitespace suffixes are silently dropped."""
    narrative = "The 3200 block of West Colfax Avenue was the scene."
    assert extract_address(narrative, city="", state_code="CO") == ("3200 West Colfax Avenue, CO")
    assert extract_address(narrative, city="Denver", state_code="") == (
        "3200 West Colfax Avenue, Denver"
    )


def test_no_match_returns_none() -> None:
    narrative = (
        "This invented record describes a person who left a residence. "
        "A vehicle appeared near Example River without an address."
    )
    # No street suffix, no block-of, no intersection trigger — nothing to grab.
    # ("Example River" is a landmark, not a street.)
    assert extract_address(narrative) is None


def test_pattern_priority_block_of_wins_over_intersection() -> None:
    """When multiple patterns match, block-of (most specific) wins."""
    narrative = (
        "The 3200 block of West Colfax Avenue near 32nd Avenue and Vine Street "
        "was searched for evidence."
    )
    assert extract_address(narrative) == "3200 West Colfax Avenue"


@pytest.mark.parametrize(
    "stype",
    [
        "Street",
        "Avenue",
        "Road",
        "Boulevard",
        "Drive",
        "Court",
        "Lane",
        "Place",
        "Way",
        "Highway",
        "Parkway",
    ],
)
def test_full_street_types(stype: Any) -> None:
    narrative = f"Officers responded to 1234 Main {stype} for a wellness check."
    result = extract_address(narrative)
    assert result is not None and stype in result


@pytest.mark.parametrize("abbr", ["St", "Ave", "Rd", "Blvd", "Dr", "Ct", "Ln", "Pl"])
def test_abbreviated_street_types(abbr: Any) -> None:
    narrative = f"Officers responded to 1234 Main {abbr} for a wellness check."
    result = extract_address(narrative)
    assert result is not None and abbr in result

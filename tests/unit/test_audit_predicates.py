import pytest

from tools.audit.predicates import (
    is_sentence_shaped,
    is_sentinel_address,
    name_would_reverse,
    narrative_has_address,
    text_has_date,
)


@pytest.mark.parametrize("text,expected", [
    ("Jennifer Kesse Missing Person Case", False),
    ("victim's nude body was discovered deceased in a road side ditch by passerby.", True),
    ("Female located with a gunshot wound on the side of the road at Squaw Place", True),
    ("Reporting Agency Information:", False),   # short, no sentence verb-ish length
    ("", False),
    (None, False),
    ("John Smith Homicide", False),
    # Legit long multi-victim titles end with the "(Agency)" tag -> NOT prose.
    ("Petra Martin and Uriel Martin Homicides (Clearwater PD)", False),
    ("Roland DeLoatch - Joseph Lee Smith Homicide (Sanford PD)", False),
    ("Avery Exampleton Homicide (Alachua CSO)", False),
])
def test_is_sentence_shaped(text: str | None, expected: bool) -> None:
    assert is_sentence_shaped(text) is expected


@pytest.mark.parametrize("name,expected", [
    ("Daniluk, Andrea Denise", False),     # has comma -> Last, First (correct)
    ("Woolsoncroft Carol", True),          # no comma -> space split reverses order
    ("Kesse, Jennifer Joyce", False),
    ("Madonna", False),                    # single token, nothing to reverse
    ("", False),
    (None, False),
])
def test_name_would_reverse(name: str | None, expected: bool) -> None:
    assert name_would_reverse(name) is expected


@pytest.mark.parametrize("addr,expected", [
    (",", True),
    ("", True),
    (".", True),
    (" , ", True),
    (None, True),
    ("501 E Bay St", False),
    ("500 W Sampleton St", False),
])
def test_is_sentinel_address(addr: str | None, expected: bool) -> None:
    assert is_sentinel_address(addr) is expected


@pytest.mark.parametrize("text,expected", [
    ("the body was found at 10207 SW 84 Ave, Gainesville", True),
    ("found at her residence", False),
    ("On 12-04-06 near SE CR 2082 at the 11000 block", True),
    ("", False),
    (None, False),
])
def test_narrative_has_address(text: str | None, expected: bool) -> None:
    assert narrative_has_address(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("On January 24, 2006, Jennifer was reported missing", True),
    ("on 12-04-06 at approximately 1:00pm", True),
    ("no date here", False),
    ("", False),
    (None, False),
])
def test_text_has_date(text: str | None, expected: bool) -> None:
    assert text_has_date(text) is expected

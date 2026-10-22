"""Unit tests for FL FDLE transform pure helpers (no DB)."""

from __future__ import annotations

import pytest

from casesignal.etl.adapters.cold_case_fl_fdle.transform import (
    _derive_narrative,
    _is_sentence_shaped,
    _synthesize_case_name,
)

# Real titles confirmed against the live FDLE source.
_DANILUK = "victim's nude body was discovered deceased in a road side ditch by passerby."
_PETTERSON = "Female located with a gunshot wound on the side of the road at Squaw Place"


@pytest.mark.parametrize("case_title,victim_name,expected", [
    # A real title always wins.
    ("Avery Exampleton Homicide (Alachua CSO)", "Exampleton, Avery",
     "Avery Exampleton Homicide (Alachua CSO)"),
    # No title -> synthesize "First Last — Type" from "Last, First".
    (None, "Exampleton, Avery", "Avery Exampleton — Homicide"),
    # Parenthetical in the surname is preserved.
    (None, "Doe (Alachua CSO), Baby Jane", "Baby Jane Doe (Alachua CSO) — Homicide"),
    # Multi-comma ("Last, First, Jr") must not fall through to the raw string.
    (None, "Smith, John, Jr", "John, Jr Smith — Homicide"),
    # No-comma single token.
    (None, "Madonna", "Madonna — Homicide"),
    # Comma-only / empty -> Unidentified.
    (None, ",", "Unidentified — Homicide (SCID1)"),
    (None, None, "Unidentified — Homicide (SCID1)"),
])
def test_synthesize_case_name(case_title: str | None, victim_name: str | None,
                              expected: str) -> None:
    assert _synthesize_case_name(case_title, victim_name, "homicide", "SCID1") == expected


def test_synthesize_case_name_skips_leaked_title() -> None:
    # When the summary leaked into the title, synthesize from the victim instead.
    assert _synthesize_case_name(
        _DANILUK, "Daniluk, Andrea Denise", "homicide", "1905", title_is_leaked=True
    ) == "Andrea Denise Daniluk — Homicide"


@pytest.mark.parametrize("text,expected", [
    (_DANILUK, True),                                            # leaked: ends "." + 13 words
    (_PETTERSON, True),                                          # leaked: 19 words
    ("Avery Exampleton Homicide (Alachua CSO)", False),           # synthetic title
    ("Petra Martin and Uriel Martin Homicides (Clearwater PD)", False),  # legit multi-victim (8 words)
    ("Roland DeLoatch - Joseph Lee Smith Homicide (Sanford PD)", False),
    ("", False),
    (None, False),
])
def test_is_sentence_shaped(text: str | None, expected: bool) -> None:
    assert _is_sentence_shaped(text) is expected


@pytest.mark.parametrize("narrative,case_title,leaked,expected", [
    ("On 12-04-06 the body was found.", _DANILUK, False, "On 12-04-06 the body was found."),
    (None, _DANILUK, True, _DANILUK),     # empty narrative + leaked title -> use the title
    ("", _DANILUK, True, _DANILUK),
    (None, "Avery Exampleton Homicide", False, ""),  # not leaked -> empty
])
def test_derive_narrative(narrative: str | None, case_title: str | None,
                          leaked: bool, expected: str) -> None:
    assert _derive_narrative(narrative, case_title, leaked) == expected

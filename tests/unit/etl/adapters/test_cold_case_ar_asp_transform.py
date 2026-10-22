"""Tests for AR ASP pure transform helpers."""

from __future__ import annotations

from typing import Any

import pytest

from casesignal.etl.adapters.cold_case_ar_asp.transform import (
    _split_display_name,
    assign_source_case_ids,
    build_extraction_text,
    derive_case_type,
    normalize_ar_date,
)


def test_normalize_ar_date_long_form() -> None:
    assert normalize_ar_date("January 14, 1991") == "1991-01-14"
    assert normalize_ar_date("June 9, 1995") == "1995-06-09"


def test_normalize_ar_date_mdy() -> None:
    assert normalize_ar_date("07/29/1994") == "1994-07-29"
    assert normalize_ar_date("7/4/1988") == "1988-07-04"


def test_normalize_ar_date_month_year_gets_day_one() -> None:
    # Consistent with normalize_date's year-only -> Jan 1 convention:
    # accepted day=1 false precision beats losing the date entirely.
    assert normalize_ar_date("December 2017") == "2017-12-01"
    assert normalize_ar_date("May 2021") == "2021-05-01"


def test_normalize_ar_date_sentinels_and_garbage() -> None:
    assert normalize_ar_date("Unknown") is None
    assert normalize_ar_date(None) is None
    assert normalize_ar_date("") is None
    assert normalize_ar_date("sometime that summer") is None


def test_derive_case_type() -> None:
    assert derive_case_type("death") == "homicide"
    assert derive_case_type("missing") == "missing_person"
    assert derive_case_type(None) == "cold_case"


def test_assign_source_case_ids_prefers_case_number() -> None:
    entries: list[dict[str, Any]] = [
        {"slug": "a-b", "case_number": "SYN-001"},
        {"slug": "c-d", "case_number": "SYN-002"},
    ]
    assign_source_case_ids(entries)
    assert entries[0]["source_case_id"] == "SYN-001"
    assert entries[1]["source_case_id"] == "SYN-002"


def test_assign_source_case_ids_falls_back_to_slug_on_missing_or_dup() -> None:
    entries: list[dict[str, Any]] = [
        {"slug": "a-b", "case_number": "DUP-1"},
        {"slug": "c-d", "case_number": "DUP-1"},
        {"slug": "e-f", "case_number": None},
    ]
    assign_source_case_ids(entries)
    assert entries[0]["source_case_id"] == "a-b"
    assert entries[1]["source_case_id"] == "c-d"
    assert entries[2]["source_case_id"] == "e-f"


def test_assign_source_case_ids_raises_on_cross_entry_collision() -> None:
    """A unique CASE NUMBER can theoretically equal another entry's slug — the
    raw table PK would then silently drop a row via ON CONFLICT DO NOTHING.
    assign_source_case_ids must catch this after assignment, not let it
    through to raw_load."""
    entries: list[dict[str, Any]] = [
        {"slug": "unique-case", "case_number": "99-001-99"},
        {"slug": "99-001-99", "case_number": None},
    ]
    with pytest.raises(ValueError, match="99-001-99"):
        assign_source_case_ids(entries)


def test_build_extraction_text_appends_cause_line() -> None:
    assert (
        build_extraction_text("Body found in a ditch.", "Strangulation")
        == "Body found in a ditch.\n\nCause of death: Strangulation."
    )
    assert build_extraction_text("Body found.", None) == "Body found."
    # No double period when the cause already ends with one
    assert build_extraction_text("X.", "Gunshot.") == "X.\n\nCause of death: Gunshot."


def test_split_display_name_plain() -> None:
    assert _split_display_name("Ada Ann Exampleton Example") == ("Ada Ann Exampleton", "Example")
    assert _split_display_name("Robin Sampleton") == ("Robin", "Sampleton")
    assert _split_display_name("Cher") == ("Cher", "")
    assert _split_display_name(None) == ("Unknown", "")


def test_split_display_name_keeps_suffix_with_surname() -> None:
    # 9 of the 148 live AR corpus names end in Jr./Sr. (e.g. "Avery L.
    # Sampleton Jr."); the suffix must stay attached to the surname, not
    # become the surname (Codex P2 on PR #249).
    assert _split_display_name("Avery L. Sampleton Jr.") == ("Avery L.", "Sampleton Jr.")
    assert _split_display_name("Samuel Brooks Jr.") == ("Samuel", "Brooks Jr.")
    assert _split_display_name("Jordan Patrick Exampleton Sr.") == ("Jordan Patrick", "Exampleton Sr.")
    assert _split_display_name("Alex Odell Sampleton III") == ("Alex Odell", "Sampleton III")


def test_split_display_name_multi_victim_stays_garbled_by_design() -> None:
    # reconcile_victims splits ' and ' names from the Tier-2 roster; the
    # source row keeps the collapsed name.
    assert _split_display_name("Alf and Bea Testford") == ("Alf and Bea", "Testford")

"""Tests for shared adapter normalizers (etl/services/normalizers.py)."""

from __future__ import annotations

from casesignal.etl.services.normalizers import (
    clean_sentinel,
    normalize_case_type,
    normalize_date,
    normalize_gender,
    normalize_race,
    split_victim_name,
    try_int,
)

# --- normalize_case_type ---


def test_normalize_case_type_hyphen_to_underscore() -> None:
    assert normalize_case_type("missing-person") == "missing_person"
    assert normalize_case_type("unidentified-person") == "unidentified_person"


def test_normalize_case_type_idempotent_on_canonical() -> None:
    for v in ("homicide", "missing_person", "cold_case", "suspicious_death"):
        assert normalize_case_type(v) == v


def test_normalize_case_type_lowercases_and_collapses() -> None:
    assert normalize_case_type("Missing Person") == "missing_person"
    assert normalize_case_type("  COLD--CASE  ") == "cold_case"


def test_normalize_case_type_empty_none() -> None:
    assert normalize_case_type(None) is None
    assert normalize_case_type("") is None
    assert normalize_case_type("   ") is None


# --- normalize_race ---


def test_normalize_race_single_word_titlecased() -> None:
    assert normalize_race("black") == "Black"
    assert normalize_race("BLACK") == "Black"
    assert normalize_race("asian") == "Asian"
    assert normalize_race("ASIAN") == "Asian"
    assert normalize_race("white") == "White"
    assert normalize_race("hispanic") == "Hispanic"
    assert normalize_race("unknown") == "Unknown"


def test_normalize_race_multiword_and_punctuated_unchanged() -> None:
    # Distinct/synonym categories preserved verbatim — no synonym merging.
    for v in (
        "American Indian or Alaska Native",
        "Black or African American",
        "White/Caucasian",
        "Hispanic/Latino",
    ):
        assert normalize_race(v) == v


def test_normalize_race_collapses_whitespace_and_empty() -> None:
    assert normalize_race("  Black  ") == "Black"
    assert normalize_race(None) is None
    assert normalize_race("") is None

# --- normalize_gender ---


def test_normalize_gender_canonical_m() -> None:
    assert normalize_gender("M") == "M"
    assert normalize_gender("Male") == "M"
    assert normalize_gender("male") == "M"
    assert normalize_gender("MALE") == "M"


def test_normalize_gender_canonical_f() -> None:
    assert normalize_gender("F") == "F"
    assert normalize_gender("Female") == "F"
    assert normalize_gender("female") == "F"


def test_normalize_gender_unknown_returns_none() -> None:
    assert normalize_gender(None) is None
    assert normalize_gender("") is None
    assert normalize_gender("Unknown") is None
    assert normalize_gender("X") is None


def test_normalize_gender_trims_whitespace() -> None:
    assert normalize_gender("  M  ") == "M"
    assert normalize_gender("  female ") == "F"


# --- normalize_date ---


def test_normalize_date_full_mdy() -> None:
    assert normalize_date("11/21/2008") == "2008-11-21"
    assert normalize_date("1/2/1999") == "1999-01-02"
    assert normalize_date("12/31/2025") == "2025-12-31"


def test_normalize_date_year_only_fallback() -> None:
    # Any 19xx/20xx token in the input becomes <year>-01-01
    assert normalize_date("circa 1987") == "1987-01-01"
    assert normalize_date("2014 cold case") == "2014-01-01"


def test_normalize_date_unparseable_returns_none() -> None:
    assert normalize_date(None) is None
    assert normalize_date("") is None
    assert normalize_date("not a date") is None
    assert normalize_date("1885") is None  # pre-1900 fallback excludes it


# --- clean_sentinel ---


def test_clean_sentinel_returns_non_sentinel() -> None:
    assert clean_sentinel("Manchester") == "Manchester"
    assert clean_sentinel("123 Main St") == "123 Main St"


def test_clean_sentinel_strips_whitespace() -> None:
    assert clean_sentinel("  Manchester  ") == "Manchester"


def test_clean_sentinel_drops_known_sentinels() -> None:
    for sentinel in ("Unknown", "unknown", "N/A", "n/a", "None", "Not Applicable", "Not Available"):
        assert clean_sentinel(sentinel) is None, f"failed on {sentinel!r}"


def test_clean_sentinel_drops_empty_and_none() -> None:
    assert clean_sentinel(None) is None
    assert clean_sentinel("") is None
    assert clean_sentinel("   ") is None


# --- try_int ---


def test_try_int_happy_path() -> None:
    assert try_int("30") == 30
    assert try_int("  42  ") == 42
    assert try_int(99) == 99


def test_try_int_returns_none_for_garbage() -> None:
    assert try_int(None) is None
    assert try_int("") is None
    assert try_int("abc") is None
    assert try_int("3.14") is None  # float strings fail


# --- split_victim_name ---


def test_split_victim_name_two_tokens() -> None:
    assert split_victim_name("Alex Exampleton") == ("Alex", "Exampleton")


def test_split_victim_name_three_or_more_tokens() -> None:
    # All-but-last become first_name; last is last_name
    assert split_victim_name("Mary Jane Smith") == ("Mary Jane", "Smith")
    assert split_victim_name("Jose de la Cruz") == ("Jose de la", "Cruz")


def test_split_victim_name_single_token() -> None:
    assert split_victim_name("Madonna") == ("Madonna", "")


def test_split_victim_name_empty_returns_unknown() -> None:
    assert split_victim_name(None) == ("Unknown", "")
    assert split_victim_name("") == ("Unknown", "")
    assert split_victim_name("   ") == ("Unknown", "")

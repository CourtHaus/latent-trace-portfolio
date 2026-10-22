"""Unit tests for victim-race canonicalization (filters.canonical_race /
expand_race_filter).

These are pure functions over source-provided race strings — a deterministic
synonym map, never inference. The KNOWN_SOURCE_VOCABULARY list mirrors the
distinct non-null values observed in cold_case.victim; the drift guard fails if
the map ever stops covering one, which would otherwise silently dump a real
spelling into the "Other" bucket.
"""

from __future__ import annotations

import pytest

from casesignal.api.services.cold_cases.filters import (
    RACE_CANONICAL_MAP,
    RACE_CANONICAL_TO_SOURCES,
    RACE_FALLBACK_CANONICAL,
    RACE_NON_OTHER_SOURCES,
    canonical_race,
    expand_race_filter,
    race_exclude_filter,
)

# (raw source spelling, expected canonical bucket). Mirrors the live vocabulary.
KNOWN_SOURCE_VOCABULARY: list[tuple[str, str]] = [
    ("Black", "Black or African American"),
    ("BLACK or AFRICAN AMERICAN", "Black or African American"),
    ("African American", "Black or African American"),
    ("White", "White"),
    ("Caucasian", "White"),
    ("White/Caucasian", "White"),
    ("White/ Caucasian", "White"),
    ("Hispanic", "Hispanic or Latino"),
    ("Hispanic or Latino", "Hispanic or Latino"),
    ("Hispanic/Latino", "Hispanic or Latino"),
    ("Asian", "Asian"),
    ("Asian or Pacific Islander", "Asian"),
    ("American Indian", "American Indian or Alaska Native"),
    ("American Indian or Alaskan Native", "American Indian or Alaska Native"),
    ("AMERICAN INDIAN or ALASKA NATIVE", "American Indian or Alaska Native"),
    ("Native American", "American Indian or Alaska Native"),
    ("Pacific Islander", "Native Hawaiian or Other Pacific Islander"),
    ("Polynesian", "Native Hawaiian or Other Pacific Islander"),
    ("Biracial", "Other"),
    ("Brown", "Other"),
    ("MIDDLE EASTERN", "Other"),
    ("Caucasian\\Hispanic or Latino", "Other"),
    ("Unknown", "Unknown"),
]


@pytest.mark.parametrize(("raw", "expected"), KNOWN_SOURCE_VOCABULARY)
def test_canonical_race_maps_known_vocabulary(raw: str, expected: str) -> None:
    assert canonical_race(raw) == expected


def test_canonical_race_is_case_and_whitespace_insensitive() -> None:
    assert canonical_race("  black  ") == "Black or African American"
    assert canonical_race("WHITE") == "White"


def test_canonical_race_unknown_value_falls_back_to_other() -> None:
    assert canonical_race("Klingon") == RACE_FALLBACK_CANONICAL
    assert RACE_FALLBACK_CANONICAL == "Other"


def test_known_vocabulary_is_fully_mapped_no_silent_fallback() -> None:
    """Drift guard: every observed source spelling must be explicitly mapped, so
    none silently lands in the catch-all 'Other' bucket via the fallback."""
    for raw, _ in KNOWN_SOURCE_VOCABULARY:
        assert raw.strip().lower() in RACE_CANONICAL_MAP, f"unmapped: {raw!r}"


def test_reverse_map_is_consistent_with_forward_map() -> None:
    for src, canon in RACE_CANONICAL_MAP.items():
        assert src in RACE_CANONICAL_TO_SOURCES[canon]


def test_expand_race_filter_bucket_to_all_source_forms() -> None:
    # Selecting the canonical bucket must match every raw spelling that folds in.
    assert expand_race_filter(["Black or African American"]) == sorted(
        ["black", "black or african american", "african american"]
    )


def test_expand_race_filter_multiple_buckets() -> None:
    out = expand_race_filter(["White", "Asian"])
    assert out is not None
    assert set(out) == {
        "white",
        "caucasian",
        "white/caucasian",
        "white/ caucasian",
        "asian",
        "asian or pacific islander",
    }


def test_expand_race_filter_tolerates_legacy_raw_value() -> None:
    # A pre-canonicalization shared link may still carry a raw spelling.
    assert expand_race_filter(["Black"]) == ["black"]


def test_expand_race_filter_drops_unknown_and_returns_none_when_empty() -> None:
    assert expand_race_filter(["Klingon"]) is None
    assert expand_race_filter([]) is None
    assert expand_race_filter(None) is None


def test_expand_race_filter_does_not_positively_expand_other() -> None:
    # "Other" is matched as a complement (race_exclude_filter), never a positive
    # list — so it must not contribute source forms to the ANY(:race) match.
    assert expand_race_filter(["Other"]) is None
    # Mixed selection: only the specific bucket's sources come through positively.
    assert expand_race_filter(["White", "Other"]) == sorted(
        ["white", "caucasian", "white/caucasian", "white/ caucasian"]
    )


def test_race_non_other_sources_excludes_other_spellings() -> None:
    # The complement set must contain the specific-bucket spellings...
    assert "black" in RACE_NON_OTHER_SOURCES
    assert "white" in RACE_NON_OTHER_SOURCES
    # ...and exclude every spelling that folds to Other, so selecting Other (=
    # "not one of these") still matches them.
    for other_src, canon in RACE_CANONICAL_MAP.items():
        if canon == RACE_FALLBACK_CANONICAL:
            assert other_src not in RACE_NON_OTHER_SOURCES


def test_race_exclude_filter_returns_complement_set_only_for_other() -> None:
    assert race_exclude_filter(["Other"]) == RACE_NON_OTHER_SOURCES
    assert race_exclude_filter(["White", "Other"]) == RACE_NON_OTHER_SOURCES
    assert race_exclude_filter(["White"]) is None
    assert race_exclude_filter([]) is None
    assert race_exclude_filter(None) is None

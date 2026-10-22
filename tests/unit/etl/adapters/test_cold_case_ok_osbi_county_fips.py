"""Tests for the OK county-name → FIPS lookup + narrative extractor."""

from __future__ import annotations

from casesignal.etl.adapters.cold_case_ok_osbi.county_fips import (
    OK_COUNTY_FIPS,
    county_from_narrative,
    lookup,
    name_for_fips,
)


def test_all_77_counties_present() -> None:
    assert len(OK_COUNTY_FIPS) == 77
    assert all(f.startswith("40") and len(f) == 5 for f in OK_COUNTY_FIPS.values())


def test_lookup_exact_and_suffix_and_case() -> None:
    assert lookup("Pottawatomie") == "40125"
    assert lookup("tulsa county") == "40143"
    assert lookup("LE FLORE") == "40079"
    assert lookup("McClain") == "40087"
    assert lookup("Nowhere") is None
    assert lookup(None) is None


def test_county_from_narrative_single_and_multiword() -> None:
    assert county_from_narrative(
        "the body was found in Pottawatomie County near I-40"
    ) == "40125"
    assert county_from_narrative("remains were located in Le Flore County") == "40079"
    assert county_from_narrative("a field in Roger Mills County, Oklahoma") == "40129"


def test_county_from_narrative_none_when_no_county_or_unknown() -> None:
    assert county_from_narrative("last seen in Tulsa, Oklahoma") is None  # city, no "County"
    assert county_from_narrative("in Fremont County") is None  # not an OK county
    assert county_from_narrative(None) is None
    assert county_from_narrative("") is None


def test_county_from_narrative_cleveland_single_real_county() -> None:
    # data/static/county_centroids.csv: OK,40027,40,Cleveland County,...
    assert county_from_narrative("in Cleveland County, Oklahoma") == "40027"


def test_county_from_narrative_multiword_exact_phrase_still_resolves() -> None:
    assert county_from_narrative("Le Flore County") == "40079"
    assert county_from_narrative("Roger Mills County") == "40129"


def test_name_for_fips_reverse_lookup() -> None:
    assert name_for_fips("40125") == "Pottawatomie"
    assert name_for_fips("99999") is None


def test_county_from_narrative_no_greedy_false_positive() -> None:
    # Old implementation: the greedy 2-word regex on "West Cleveland County"
    # captured "West Cleveland", failed the direct lookup, then fell back to
    # the rsplit last word "Cleveland" and returned 40027 on the FIRST
    # match — short-circuiting before ever reaching the unambiguous "Le
    # Flore County" mention later in the same narrative. (Verified against
    # the old regex directly: it returns "40027" for this exact string.)
    # New implementation checks the known multi-word county names across the
    # whole narrative first, so it correctly resolves to Le Flore instead of
    # stopping on the fragile single-word fallback for a bogus "West
    # Cleveland" grab.
    text = (
        "last seen near West Cleveland County before remains were found "
        "in Le Flore County"
    )
    assert county_from_narrative(text) == "40079"


def test_normalized_index_has_no_collisions() -> None:
    # Every OK county must remain distinct under (no-spaces, lowercase)
    # normalization, else lookup() could resolve to the wrong county.
    from casesignal.etl.adapters.cold_case_ok_osbi.county_fips import _NORMALIZED_TO_FIPS

    assert len(_NORMALIZED_TO_FIPS) == 77


def test_lookup_leflore_spelling_variants() -> None:
    # OSBI prose uses "LeFlore"/"Leflore" for the canonical "Le Flore".
    assert lookup("Le Flore") == "40079"
    assert lookup("LeFlore") == "40079"
    assert lookup("Leflore") == "40079"
    assert lookup("leflore county") == "40079"


def test_county_from_narrative_concatenated_leflore() -> None:
    # Synthetic narrative retaining the concatenated county spelling.
    assert (
        county_from_narrative(
            'James "Arthur" Sampleton was found on a roadside in LeFlore County on February 21, 2001'
        )
        == "40079"
    )


def test_county_from_narrative_leflore_wins_over_later_county() -> None:
    # The exact bug Codex flagged: a mis-spelled earlier county must not be
    # skipped in favor of a correctly-spelled LATER one.
    assert (
        county_from_narrative("last seen in LeFlore County, later found in McCurtain County")
        == "40079"
    )


def test_county_from_narrative_earliest_wins_across_forms() -> None:
    # Codex #2: an earlier concatenated-spelling county must win over a later
    # correctly-spaced multi-word county — document order, not form priority.
    assert (
        county_from_narrative("in LeFlore County, then later Roger Mills County")
        == "40079"
    )
    # And the reverse: earlier spaced multi-word wins over a later single.
    assert (
        county_from_narrative("in Roger Mills County, then Cleveland County") == "40129"
    )

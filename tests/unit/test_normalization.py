"""Race canonicalization lives in a neutral module importable by both the
API layer and the correlation engine (no api->correlation import cycle)."""

from __future__ import annotations

from casesignal.normalization import (
    RACE_CANONICAL_MAP,
    RACE_FALLBACK_CANONICAL,
    RACE_UNKNOWN_CANONICAL,
    canonical_race,
)


def test_canonical_race_folds_known_spellings() -> None:
    assert canonical_race("BLACK or AFRICAN AMERICAN") == "Black or African American"
    assert canonical_race("black") == "Black or African American"
    assert canonical_race("Caucasian") == "White"


def test_canonical_race_unknown_spelling_falls_back_to_other() -> None:
    assert canonical_race("Martian") == RACE_FALLBACK_CANONICAL == "Other"


def test_unknown_bucket_constant() -> None:
    assert canonical_race("unknown") == RACE_UNKNOWN_CANONICAL == "Unknown"


def test_filters_module_reexports_for_api_compat() -> None:
    # The API filters module keeps working against the moved symbols.
    from casesignal.api.services.cold_cases import filters

    assert filters.canonical_race is canonical_race
    assert filters.RACE_CANONICAL_MAP is RACE_CANONICAL_MAP

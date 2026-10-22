"""Integration tests for base_rates._compute_base_rates and get_base_rates.

Assertions are background-data-proof: we check canonicalization/exclusion
properties and presence of seeded values, NOT orderings that background
rows could flip.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from casesignal.correlation.base_rates import (
    _compute_base_rates,
    clear_base_rates_cache,
    get_base_rates,
)
from casesignal.etl.services.db import create_session_factory
from tests.integration._seed import (
    CaseSpec,
    ExtractionSpec,
    SeedFn,
    VictimSpec,
)

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


@pytest.fixture
def session_factory(db_engine: Any) -> Any:
    return create_session_factory(db_engine)


def test_base_rates_exclusion_and_canonicalization(
    seed: SeedFn, session_factory: Any
) -> None:
    """Seeded values appear in weights; unknowns and nulls are excluded;
    race is canonicalized before counting."""
    clear_base_rates_cache()
    try:
        seed(
            "br-base",
            [
                # Case 1: firearm weapon, M gender, "Black" race
                CaseSpec(
                    source_case_id="br1",
                    case_name="BR Case 1",
                    state="MD",
                    victims=[VictimSpec(first_name="BROne", last_name="Victim", gender="M", race="Black")],
                    extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="public_outdoor")],
                ),
                # Case 2: firearm weapon, M gender, "BLACK or AFRICAN AMERICAN" race
                # (different spelling, same canonical bucket as case 1)
                CaseSpec(
                    source_case_id="br2",
                    case_name="BR Case 2",
                    state="MD",
                    victims=[VictimSpec(first_name="BRTwo", last_name="Victim", gender="M", race="BLACK or AFRICAN AMERICAN")],
                    extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
                ),
                # Case 3: knife weapon, F gender, "Unknown" race (unknown = excluded)
                CaseSpec(
                    source_case_id="br3",
                    case_name="BR Case 3",
                    state="MD",
                    victims=[VictimSpec(first_name="BRThree", last_name="Victim", gender="F", race="Unknown")],
                    extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type=None)],
                ),
                # Case 4: unknown weapon, NULL gender, NULL race (all excluded)
                CaseSpec(
                    source_case_id="br4",
                    case_name="BR Case 4",
                    state="MD",
                    victims=[VictimSpec(first_name="BRFour", last_name="Victim", gender=None, race=None)],
                    extractions=[ExtractionSpec(prompt_tier=1, weapon="unknown", location_type=None)],
                ),
                # Case 5: second race bucket. Without it the corpus has exactly
                # one race bucket, whose weight is -log2(1) = -0.0 — the
                # "all weights positive" assertion below is unsatisfiable on an
                # empty DB (it only ever passed on databases where residue from
                # other tests provided the diversity).
                CaseSpec(
                    source_case_id="br5",
                    case_name="BR Case 5",
                    state="MD",
                    victims=[VictimSpec(first_name="BRFive", last_name="Victim", gender="M", race="White")],
                    extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
                ),
            ],
        )

        with session_factory() as session:
            rates = _compute_base_rates(session)

        # Weapon: seeded "firearm" and "knife" must appear; "unknown" must not
        assert {"firearm", "knife"} <= set(rates.weapon)
        assert "unknown" not in rates.weapon
        # Location: seeded "public_outdoor" and "residence" must appear
        assert {"public_outdoor", "residence"} <= set(rates.location_type)

        # Race: "Black or African American" canonical bucket must appear;
        # raw "Unknown" is excluded so its canonical form must not appear
        assert "Black or African American" in rates.victim_race
        assert "Unknown" not in rates.victim_race

        # All weights must be positive
        for w in rates.weapon.values():
            assert w > 0, f"weapon weight not positive: {w}"
        for w in rates.location_type.values():
            assert w > 0, f"location_type weight not positive: {w}"
        for w in rates.victim_gender.values():
            assert w > 0, f"victim_gender weight not positive: {w}"
        for w in rates.victim_race.values():
            assert w > 0, f"victim_race weight not positive: {w}"

        # age_close_weight is non-negative (may be 0 if no age_num data)
        assert rates.age_close_weight >= 0

    finally:
        clear_base_rates_cache()


def test_get_base_rates_ttl_cache(seed: SeedFn, session_factory: Any) -> None:
    """get_base_rates returns the same object on a second call within TTL."""
    clear_base_rates_cache()
    try:
        seed(
            "br-cache",
            [
                CaseSpec(
                    source_case_id="brc1",
                    case_name="BR Cache Case",
                    state="MD",
                    victims=[VictimSpec(first_name="BRCacheOne", last_name="Victim", gender="M", race="White")],
                    extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
                ),
            ],
        )

        with session_factory() as session:
            first = get_base_rates(session)
        with session_factory() as session:
            second = get_base_rates(session)

        assert first is second, "get_base_rates should return the same cached object within TTL"

    finally:
        clear_base_rates_cache()

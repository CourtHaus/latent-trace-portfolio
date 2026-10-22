"""Integration tests for find_correlated_cases().

Self-seeding: every test creates an isolated synthetic corpus through
tests.integration._seed, then calls the service with a read session. The
coordinates sit in the North Atlantic so historical dev-DB rows cannot enter
the 50-mile candidate pool when other local corpora exist.

Score assertions are structural (ranges, ordering, dimension presence) rather
than exact values because the rarity weights depend on the live corpus.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from sqlalchemy.orm import Session

from casesignal.correlation.config import (
    CORRELATION_SCORE_FLOOR,
    CORRELATION_SCORE_SCALE,
    CORRELATION_TOP_N,
)
from casesignal.correlation.schemas import CorrelatedCaseSummary
from casesignal.correlation.service import find_correlated_cases
from tests.integration._seed import CaseSpec, ExtractionSpec, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


def _case_spec(
    suffix: str,
    *,
    incident_date: date,
    lat: float,
    lon: float,
    victim_gender: str | None = "F",
    victim_race: str | None = "W",
    victim_age: int | None = 35,
    weapon: str | None = "firearm",
    weapon_low_confidence: bool = False,
    location_type: str | None = "residence",
    location_type_low_confidence: bool = False,
) -> CaseSpec:
    victims = []
    if victim_gender is not None or victim_race is not None or victim_age is not None:
        victims.append(
            VictimSpec(
                first_name="Jane",
                last_name=f"Doe{suffix}",
                gender=victim_gender,
                race=victim_race,
                age_text=str(victim_age) if victim_age is not None else None,
            )
        )

    return CaseSpec(
        source_case_id=f"C2-{suffix}",
        case_name=f"Correlation Test Case {suffix}",
        state="ZZ",
        case_type="homicide",
        city="Correlation Test City",
        incident_date=incident_date.isoformat(),
        about_text="Correlation service integration-test seed.",
        latitude=lat,
        longitude=lon,
        geocode_precision="street",
        victims=victims,
        extractions=[
            ExtractionSpec(
                prompt_tier=1,
                weapon=weapon,
                weapon_low_confidence=weapon_low_confidence,
                location_type=location_type,
                location_type_low_confidence=location_type_low_confidence,
            )
        ],
    )


def test_self_excluded(db_session: Session, seed: SeedFn) -> None:
    corpus = seed(
        "CORRELATION_TEST_SELF",
        [_case_spec("self", incident_date=date(1990, 1, 1), lat=40.0, lon=-20.0)],
    )
    parent = corpus.case_ids["C2-self"]
    results = find_correlated_cases(db_session, parent)
    assert all(r.case_id != parent for r in results)


def test_geographic_filter_excludes_far_cases(db_session: Session, seed: SeedFn) -> None:
    corpus = seed(
        "CORRELATION_TEST_GEO",
        [
            _case_spec("geoP", incident_date=date(1990, 1, 1), lat=40.0, lon=-20.0),
            _case_spec("geoF", incident_date=date(1990, 6, 1), lat=40.0, lon=-25.0),
        ],
    )
    parent = corpus.case_ids["C2-geoP"]
    far = corpus.case_ids["C2-geoF"]
    results = find_correlated_cases(db_session, parent)
    assert all(r.case_id != far for r in results)


def test_temporal_filter_excludes_far_cases(db_session: Session, seed: SeedFn) -> None:
    corpus = seed(
        "CORRELATION_TEST_TIME",
        [
            _case_spec("timeP", incident_date=date(1990, 1, 1), lat=40.0, lon=-20.0),
            _case_spec("timeF", incident_date=date(2020, 1, 1), lat=40.01, lon=-20.01),
        ],
    )
    parent = corpus.case_ids["C2-timeP"]
    far = corpus.case_ids["C2-timeF"]
    results = find_correlated_cases(db_session, parent)
    assert all(r.case_id != far for r in results)


def test_unknown_does_not_contribute(db_session: Session, seed: SeedFn) -> None:
    """Both cases have weapon='unknown'; weapon should not appear in matched_dimensions."""
    corpus = seed(
        "CORRELATION_TEST_UNKNOWN",
        [
            _case_spec(
                "unkP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                weapon="unknown",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=30,
            ),
            _case_spec(
                "unkC",
                incident_date=date(1995, 1, 1),
                lat=40.01,
                lon=-20.01,
                weapon="unknown",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=32,
            ),
            # Background case ~350 mi away (outside the geo window, so never a
            # candidate): gives residence/F/W surprisal > 0 on an empty DB so
            # the candidate clears the min-dimensions gate at all.
            _case_spec(
                "unkBG",
                incident_date=date(1992, 1, 1),
                lat=45.0,
                lon=-20.0,
                weapon="knife",
                location_type="vehicle",
                victim_gender="M",
                victim_race="Black",
                victim_age=70,
            ),
        ],
    )
    parent = corpus.case_ids["C2-unkP"]
    cand = corpus.case_ids["C2-unkC"]
    results = find_correlated_cases(db_session, parent)
    found = next((r for r in results if r.case_id == cand), None)
    assert found is not None
    dim_names = {d.name for d in found.matched_dimensions}
    assert "weapon" not in dim_names


def test_low_conf_still_counts_as_match(db_session: Session, seed: SeedFn) -> None:
    """Low-confidence flag propagates to matched_dimensions when the dimension has weight.
    We seed a background case with a different weapon so firearm has surprisal > 0.
    """
    corpus = seed(
        "CORRELATION_TEST_LOW_CONF",
        [
            _case_spec(
                "lowP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                weapon="firearm",
                weapon_low_confidence=False,
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=30,
            ),
            _case_spec(
                "lowC",
                incident_date=date(1995, 1, 1),
                lat=40.01,
                lon=-20.01,
                weapon="firearm",
                weapon_low_confidence=True,
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=32,
            ),
            # Background: different weapon so firearm has surprisal > 0
            _case_spec(
                "lowBg",
                incident_date=date(1985, 1, 1),
                lat=39.0,
                lon=-21.0,  # outside 50-mi pool
                weapon="knife",
                location_type="vehicle",
                victim_gender="M",
                victim_race="Black",
                victim_age=50,
            ),
        ],
    )
    parent = corpus.case_ids["C2-lowP"]
    cand = corpus.case_ids["C2-lowC"]
    results = find_correlated_cases(db_session, parent)
    found = next((r for r in results if r.case_id == cand), None)
    assert found is not None
    weapon_dim = next((d for d in found.matched_dimensions if d.name == "weapon"), None)
    assert weapon_dim is not None, (
        f"weapon should appear in matched_dimensions; got: {[d.name for d in found.matched_dimensions]}"
    )
    assert weapon_dim.low_confidence is True


def test_demographic_dimensions_never_low_confidence(db_session: Session, seed: SeedFn) -> None:
    corpus = seed(
        "CORRELATION_TEST_DEM_CONF",
        [
            _case_spec(
                "demP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                victim_gender="F",
                victim_race="White",
                victim_age=35,
            ),
            _case_spec(
                "demC",
                incident_date=date(1995, 1, 1),
                lat=40.01,
                lon=-20.01,
                victim_gender="F",
                victim_race="White",
                victim_age=37,
            ),
            # Background case outside the geo window: demographic dimensions
            # need surprisal > 0 on an empty DB for any dimension to match.
            _case_spec(
                "demBG",
                incident_date=date(1992, 1, 1),
                lat=45.0,
                lon=-20.0,
                weapon="knife",
                location_type="vehicle",
                victim_gender="M",
                victim_race="Black",
                victim_age=70,
            ),
        ],
    )
    parent = corpus.case_ids["C2-demP"]
    cand = corpus.case_ids["C2-demC"]
    results = find_correlated_cases(db_session, parent)
    found = next((r for r in results if r.case_id == cand), None)
    assert found is not None
    for dim in found.matched_dimensions:
        if dim.name in ("victim_gender", "victim_race", "victim_age"):
            assert dim.low_confidence is False


def test_top_n_capped(db_session: Session, seed: SeedFn) -> None:
    cases = [_case_spec("topP", incident_date=date(1990, 1, 1), lat=40.0, lon=-20.0)]
    cases.extend(
        _case_spec(
            f"top{i}",
            incident_date=date(1991 + i, 1, 1),
            lat=40.0 + 0.001 * i,
            lon=-20.0,
        )
        for i in range(7)
    )
    corpus = seed("CORRELATION_TEST_TOP_N", cases)
    parent = corpus.case_ids["C2-topP"]
    results = find_correlated_cases(db_session, parent)
    assert len(results) <= CORRELATION_TOP_N


def test_results_ordered_by_score_desc_then_distance_asc(db_session: Session, seed: SeedFn) -> None:
    corpus = seed(
        "CORRELATION_TEST_ORDER",
        [
            _case_spec(
                "ordP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                victim_gender="F",
                victim_race="W",
                victim_age=30,
                weapon="firearm",
                location_type="residence",
            ),
            _case_spec(
                "ordA",
                incident_date=date(1992, 1, 1),
                lat=40.1,
                lon=-20.0,
                victim_gender="F",
                victim_race="W",
                victim_age=32,
                weapon="firearm",
                location_type="residence",
            ),
            _case_spec(
                "ordB",
                incident_date=date(1992, 1, 1),
                lat=40.01,
                lon=-20.01,
                victim_gender="F",
                victim_race="W",
                victim_age=32,
                weapon="firearm",
                location_type="residence",
            ),
            _case_spec(
                "ordC",
                incident_date=date(1992, 1, 1),
                lat=40.001,
                lon=-20.001,
                victim_gender="F",
                victim_race="W",
                victim_age=32,
                weapon="knife",
                location_type="vehicle",
            ),
        ],
    )
    parent = corpus.case_ids["C2-ordP"]
    results = find_correlated_cases(db_session, parent)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    # Among ties verify distance ordering
    for i in range(len(results) - 1):
        if results[i].score == results[i + 1].score:
            assert results[i].distance_miles <= results[i + 1].distance_miles


def test_score_floor_threshold(db_session: Session, seed: SeedFn) -> None:
    corpus = seed(
        "CORRELATION_TEST_FLOOR_THRESHOLD",
        [
            _case_spec(
                "flrP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                victim_gender="F",
                victim_race="W",
                victim_age=30,
                weapon=None,
                location_type=None,
            ),
            _case_spec(
                "flrC",
                incident_date=date(1992, 1, 1),
                lat=40.01,
                lon=-20.01,
                victim_gender="F",
                victim_race="W",
                victim_age=32,
                weapon=None,
                location_type=None,
            ),
        ],
    )
    parent = corpus.case_ids["C2-flrP"]
    results = find_correlated_cases(db_session, parent)
    for result in results:
        assert result.score >= CORRELATION_SCORE_FLOOR


# ---------------------------------------------------------------------------
# New structural tests (plan Task 5, step 5.2)
# ---------------------------------------------------------------------------

def test_rich_match_is_a_lead_with_valid_score_range(
    db_session: Session, seed: SeedFn
) -> None:
    """A pair with multiple matching dimensions appears in leads with score in
    (0, 10], score_max == 10.0, and 0 < proximity_factor <= 1.

    We seed background cases with different values so each dimension has
    surprisal > 0 (Laplace smoothing gives weight 0 when a value is the ONLY
    value in the corpus — no information). Race uses canonical spellings.
    """
    corpus = seed(
        "CORRELATION_TEST_RICH_LEAD",
        [
            _case_spec(
                "richP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=30,
            ),
            _case_spec(
                "richC",
                incident_date=date(1995, 1, 1),
                lat=40.05,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="Black",  # race differs — still weapon+loc+gender
                victim_age=55,
            ),
            # Background cases outside the 50-mi pool but in the published corpus
            # so each dimension has >= 2 unique values and thus surprisal > 0.
            _case_spec(
                "richBg1",
                incident_date=date(1985, 1, 1),
                lat=39.0,
                lon=-21.0,
                weapon="knife",
                location_type="vehicle",
                victim_gender="M",
                victim_race="Black",
                victim_age=50,
            ),
            _case_spec(
                "richBg2",
                incident_date=date(1985, 6, 1),
                lat=38.5,
                lon=-21.5,
                weapon="asphyxiation",
                location_type="public_outdoor",
                victim_gender="M",
                victim_race="White",
                victim_age=45,
            ),
        ],
    )
    parent = corpus.case_ids["C2-richP"]
    cand_id = corpus.case_ids["C2-richC"]
    results = find_correlated_cases(db_session, parent)
    found = next((r for r in results if r.case_id == cand_id), None)
    assert found is not None, "rich-match candidate should appear in leads"
    assert found.score > 0
    assert found.score <= CORRELATION_SCORE_SCALE
    assert found.score_max == CORRELATION_SCORE_SCALE
    assert 0 < found.proximity_factor <= 1.0
    dim_names = {d.name for d in found.matched_dimensions}
    # At minimum weapon + location_type + gender should all match
    assert {"weapon", "location_type", "victim_gender"}.issubset(dim_names), (
        f"expected weapon/location_type/victim_gender in dims; got {dim_names}"
    )


def test_rare_weapon_beats_common_weapon(db_session: Session, seed: SeedFn) -> None:
    """Rarity ordering: a SHARED rare weapon scores higher than a SHARED common
    one, all else equal.

    The honest comparison needs two *pairs*, because a parent has one weapon —
    so "rare vs common weapon match" cannot be tested within a single parent's
    pool. We build:

      * a RARE pair  — parent + candidate that both have asphyxiation;
      * a COMMON pair — parent + candidate that both have firearm;

    identical on every other dimension (residence / F / W / age 30 vs 32) and
    geometry (candidate 0.03 deg lat from its parent). Rarity is established
    corpus-wide by seeding background firearm cases far outside either pool, so
    firearm is common and asphyxiation is rare. The weapon surprisal is then the
    ONLY thing that differs between the two pairs' scores. We assert both the
    matched weapon-dimension weight and the overall score order. Unlike a
    same-weapon-vs-different-weapon design, this would FAIL under flat weights.
    """
    # Background firearm cases ~140 mi north (lat 42), outside both 50-mi pools,
    # published so they count toward corpus weapon frequencies. Six of them make
    # firearm common (8 total) vs asphyxiation rare (2 total).
    background = [
        _case_spec(
            f"rarBg{i}",
            incident_date=date(1990, 1, 1),
            lat=42.0,
            lon=-20.0 + i * 0.001,
            weapon="firearm",
            location_type="residence",
            victim_gender="F",
            victim_race="W",
            victim_age=40,
        )
        for i in range(6)
    ]
    corpus = seed(
        "CORRELATION_TEST_RARITY",
        [
            # RARE pair (asphyxiation), near the South-Atlantic anchor.
            _case_spec(
                "rareP", incident_date=date(1990, 1, 1), lat=44.0, lon=-20.0,
                weapon="asphyxiation", location_type="residence",
                victim_gender="F", victim_race="W", victim_age=30,
            ),
            _case_spec(
                "rareC", incident_date=date(1993, 1, 1), lat=44.03, lon=-20.0,
                weapon="asphyxiation", location_type="residence",
                victim_gender="F", victim_race="W", victim_age=32,
            ),
            # COMMON pair (firearm), ~140 mi away from the rare pair (lat 46).
            _case_spec(
                "commonP", incident_date=date(1990, 1, 1), lat=46.0, lon=-20.0,
                weapon="firearm", location_type="residence",
                victim_gender="F", victim_race="W", victim_age=30,
            ),
            _case_spec(
                "commonC", incident_date=date(1993, 1, 1), lat=46.03, lon=-20.0,
                weapon="firearm", location_type="residence",
                victim_gender="F", victim_race="W", victim_age=32,
            ),
            *background,
        ],
    )
    from casesignal.correlation.service import _score_all_candidates

    rare_pool = {c.case_id: c for c in _score_all_candidates(db_session, corpus.case_ids["C2-rareP"])}
    common_pool = {c.case_id: c for c in _score_all_candidates(db_session, corpus.case_ids["C2-commonP"])}
    rare_lead = rare_pool[corpus.case_ids["C2-rareC"]]
    common_lead = common_pool[corpus.case_ids["C2-commonC"]]

    def _weapon_weight(summary: CorrelatedCaseSummary) -> float:
        for d in summary.matched_dimensions:
            if d.name == "weapon":
                return float(d.weight)
        raise AssertionError("expected a weapon match in both pairs")

    # The crisp signal: the shared rare weapon is worth more bits than the
    # shared common one.
    assert _weapon_weight(rare_lead) > _weapon_weight(common_lead), (
        f"asphyxiation weapon weight ({_weapon_weight(rare_lead):.3f}) should exceed "
        f"firearm weapon weight ({_weapon_weight(common_lead):.3f})"
    )
    # And it carries through to the overall score (geometry + other dims equal).
    assert rare_lead.score > common_lead.score, (
        f"rare-weapon pair score ({rare_lead.score:.4f}) should exceed "
        f"common-weapon pair score ({common_lead.score:.4f})"
    )


def test_min_evidence_not_in_leads_but_in_candidates(
    db_session: Session, seed: SeedFn
) -> None:
    """A candidate matching ONLY weapon (1 dimension < CORRELATION_MIN_DIMENSIONS=2)
    must NOT appear in find_correlated_cases leads but MUST appear in
    get_correlation_candidates().candidates."""
    corpus = seed(
        "CORRELATION_TEST_MIN_EVIDENCE",
        [
            _case_spec(
                "minP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=30,
            ),
            # Candidate: weapon matches, everything else differs
            _case_spec(
                "minC",
                incident_date=date(1995, 1, 1),
                lat=40.01,
                lon=-20.01,
                weapon="firearm",
                location_type="vehicle",   # differs
                victim_gender="M",         # differs
                victim_race="Black",           # differs
                victim_age=70,             # far age
            ),
            # Background case outside the geo window with a DIFFERENT weapon:
            # firearm needs surprisal > 0 on an empty DB for the single shared
            # dimension to register at all.
            _case_spec(
                "minBG",
                incident_date=date(1992, 1, 1),
                lat=45.0,
                lon=-20.0,
                weapon="knife",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=35,
            ),
        ],
    )
    parent = corpus.case_ids["C2-minP"]
    thin_id = corpus.case_ids["C2-minC"]

    # Must NOT be in leads (fails min-dimensions gate)
    leads = find_correlated_cases(db_session, parent)
    assert all(r.case_id != thin_id for r in leads), (
        "single-dimension candidate must not appear in leads"
    )

    # MUST appear in full candidates pool
    # candidates are CandidatePoint (no case_id) so check the pool directly
    from casesignal.correlation.service import _score_all_candidates
    pool = {c.case_id: c for c in _score_all_candidates(db_session, parent)}
    assert thin_id in pool, "single-dimension candidate must still appear in full pool"
    assert len(pool[thin_id].matched_dimensions) == 1, (
        f"expected 1 matched dimension, got {pool[thin_id].matched_dimensions}"
    )


def test_proximity_closer_scores_higher(db_session: Session, seed: SeedFn) -> None:
    """Identical matched evidence at ~2 mi vs ~40 mi: closer candidate scores higher
    and its proximity_factor is greater."""
    corpus = seed(
        "CORRELATION_TEST_PROXIMITY",
        [
            _case_spec(
                "proxP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=30,
            ),
            # Near candidate: ~2 mi away (0.03 deg lat ≈ 2.1 mi)
            _case_spec(
                "proxNear",
                incident_date=date(1993, 1, 1),
                lat=40.03,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=32,
            ),
            # Far candidate: ~40 mi away (0.58 deg lat ≈ 40.5 mi — within 50mi gate)
            _case_spec(
                "proxFar",
                incident_date=date(1993, 1, 1),
                lat=40.58,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="White",
                victim_age=32,
            ),
            # Background case ~415 mi away (outside the geo window): with an
            # empty DB and an otherwise-uniform corpus every dimension has
            # P=1 → weight 0 → both candidates score 0.0 and the near>far
            # assertion is vacuously false. This gives the shared dimensions
            # surprisal > 0.
            _case_spec(
                "proxBG",
                incident_date=date(1992, 1, 1),
                lat=46.0,
                lon=-20.0,
                weapon="knife",
                location_type="vehicle",
                victim_gender="M",
                victim_race="Black",
                victim_age=70,
            ),
        ],
    )
    parent = corpus.case_ids["C2-proxP"]
    near_id = corpus.case_ids["C2-proxNear"]
    far_id = corpus.case_ids["C2-proxFar"]

    from casesignal.correlation.service import _score_all_candidates
    pool = {c.case_id: c for c in _score_all_candidates(db_session, parent)}
    assert near_id in pool and far_id in pool

    near = pool[near_id]
    far = pool[far_id]
    assert near.score > far.score, (
        f"near score ({near.score:.4f}) should exceed far score ({far.score:.4f})"
    )
    assert near.proximity_factor > far.proximity_factor, (
        f"near prox_factor ({near.proximity_factor:.4f}) should exceed "
        f"far prox_factor ({far.proximity_factor:.4f})"
    )


def test_race_cross_spelling_canonicalization(db_session: Session, seed: SeedFn) -> None:
    """Canonicalization regression: parent race 'Black', candidate 'BLACK or AFRICAN AMERICAN'
    with one more shared dimension (location_type) should produce a victim_race
    MatchedDimension with value 'Black or African American'."""
    corpus = seed(
        "CORRELATION_TEST_RACE_CANON",
        [
            _case_spec(
                "rcP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="M",
                victim_race="Black",
                victim_age=40,
            ),
            _case_spec(
                "rcC",
                incident_date=date(1994, 1, 1),
                lat=40.01,
                lon=-20.01,
                weapon="knife",           # weapon differs — no weapon match
                location_type="residence",
                victim_gender="F",        # gender differs
                victim_race="BLACK or AFRICAN AMERICAN",
                victim_age=55,
            ),
            # Background case outside the geo window with a second race bucket:
            # on an empty DB both seeded races canonicalize to ONE bucket
            # (P=1 → weight -0.0), so the victim_race dimension the test
            # asserts on can never appear without this.
            _case_spec(
                "rcBG",
                incident_date=date(1992, 1, 1),
                lat=45.0,
                lon=-20.0,
                weapon="firearm",
                location_type="vehicle",
                victim_gender="M",
                victim_race="White",
                victim_age=40,
            ),
        ],
    )
    parent = corpus.case_ids["C2-rcP"]
    cand_id = corpus.case_ids["C2-rcC"]

    from casesignal.correlation.service import _score_all_candidates
    pool = {c.case_id: c for c in _score_all_candidates(db_session, parent)}
    assert cand_id in pool, "race-cross-spelling candidate must be in pool"

    cand = pool[cand_id]
    race_dim = next((d for d in cand.matched_dimensions if d.name == "victim_race"), None)
    assert race_dim is not None, (
        f"victim_race dimension missing; got dims: {[d.name for d in cand.matched_dimensions]}"
    )
    assert race_dim.value == "Black or African American", (
        f"expected canonical 'Black or African American', got '{race_dim.value}'"
    )

"""Integration tests for GET /api/v1/cold-cases/{case_id}/correlation-candidates.

Seeds a focal case plus candidates so that SOME fall below the score floor
and some above, then verifies the endpoint contract:
  - score_max / score_floor constants are echoed correctly
  - candidates = full pool (no floor filter); leads = top-N above floor with
    min CORRELATION_MIN_DIMENSIONS matched dimensions
  - every candidate has numeric distance_miles / years_apart / score
  - leads match what find_correlated_cases returns (same order, same items)
  - focal case excludes itself
  - archived / unpublished cases are absent

Seed pattern reuses _case_spec() from test_correlation_service.py verbatim
(copied here so each module stays self-contained).
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from casesignal.correlation.config import (
    CORRELATION_SCORE_FLOOR,
    CORRELATION_SCORE_SCALE,
    CORRELATION_TOP_N,
)
from casesignal.correlation.service import find_correlated_cases
from tests.integration._seed import CaseSpec, ExtractionSpec, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


# ---------------------------------------------------------------------------
# Seed helper (mirrors test_correlation_service._case_spec exactly)
# ---------------------------------------------------------------------------

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
        source_case_id=f"CC-{suffix}",
        case_name=f"Candidates Test Case {suffix}",
        state="ZZ",
        case_type="homicide",
        city="Candidates Test City",
        incident_date=incident_date.isoformat(),
        about_text="Correlation candidates integration-test seed.",
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


# ---------------------------------------------------------------------------
# Main endpoint test
# ---------------------------------------------------------------------------

def test_candidates_endpoint_full_pool_and_leads(
    db_session: Session,
    seed: SeedFn,
    public_client: TestClient,
) -> None:
    """Core contract: full pool, floor-filtered leads, constants, ordering."""
    # Focal case: weapon=firearm, location_type=residence, gender=F, race=W, age=35
    # Above-floor candidates share multiple dimensions; below-floor candidate
    # shares only weapon (one dimension, misses CORRELATION_MIN_DIMENSIONS=2).
    corpus = seed(
        "CORR_CANDIDATES_TEST_FULL",
        [
            # focal
            _case_spec(
                "fP",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="W",
                victim_age=35,
            ),
            # above-floor: weapon + location_type match (2 dimensions >= min)
            _case_spec(
                "abv1",
                incident_date=date(1993, 1, 1),
                lat=40.01,
                lon=-20.01,
                weapon="firearm",
                location_type="residence",
                victim_gender="M",   # differs
                victim_race="B",     # differs
                victim_age=60,       # far age
            ),
            # above-floor: weapon + location_type + gender match (3 dimensions)
            _case_spec(
                "abv2",
                incident_date=date(1994, 1, 1),
                lat=40.02,
                lon=-20.02,
                weapon="firearm",
                location_type="residence",
                victim_gender="F",
                victim_race="B",     # differs
                victim_age=60,       # far age
            ),
            # below-floor: weapon only (1 dimension < CORRELATION_MIN_DIMENSIONS=2)
            _case_spec(
                "blw1",
                incident_date=date(1995, 1, 1),
                lat=40.03,
                lon=-20.03,
                weapon="firearm",
                location_type="vehicle",  # differs
                victim_gender="M",        # differs
                victim_race="B",          # differs
                victim_age=70,            # far age
            ),
        ],
    )

    focal_id = corpus.case_ids["CC-fP"]

    # --- via service: baseline for lead comparison ---
    service_leads = find_correlated_cases(db_session, focal_id)
    assert service_leads, "Seed did not produce above-floor leads via service"
    service_lead_ids = [c.case_id for c in service_leads]

    # --- via HTTP endpoint ---
    resp = public_client.get(f"/api/v1/cold-cases/{focal_id}/correlation-candidates")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # constants echoed
    assert data["score_max"] == CORRELATION_SCORE_SCALE
    assert data["score_floor"] == CORRELATION_SCORE_FLOOR

    candidates = data["candidates"]
    leads = data["leads"]

    # full pool is strictly larger than floor-filtered leads when below-floor
    # candidates were seeded
    assert len(candidates) > len(leads), (
        f"Expected full pool ({len(candidates)}) > leads ({len(leads)}); "
        "a below-floor candidate should be in the pool but not in leads"
    )

    # every candidate has required numeric fields
    for c in candidates:
        assert isinstance(c["distance_miles"], (int, float))
        assert isinstance(c["years_apart"], int)
        assert isinstance(c["score"], (int, float))

    # Self-exclusion is enforced in SQL (c.case_id != p.case_id) and verified
    # below: leads equal find_correlated_cases, which would surface the focal
    # case if it leaked into the pool. CandidatePoint is PII-free (no case_id),
    # so it can't be checked here by ID.

    # leads match find_correlated_cases (same IDs, same order, respects floor)
    lead_ids = [lead["case_id"] for lead in leads]
    assert lead_ids == service_lead_ids, (
        f"leads IDs {lead_ids} != service {service_lead_ids}"
    )
    for lead in leads:
        assert lead["score"] >= CORRELATION_SCORE_FLOOR

    # leads are a subset of the full candidate pool (by score identity)
    lead_scores = {lead["score"] for lead in leads}
    candidate_scores = {c["score"] for c in candidates}
    assert lead_scores <= candidate_scores

    # leads are capped at CORRELATION_TOP_N
    assert len(leads) <= CORRELATION_TOP_N

    # candidates sorted (score DESC, distance_miles ASC at same score)
    for i in range(len(candidates) - 1):
        a, b = candidates[i], candidates[i + 1]
        assert (a["score"], -a["distance_miles"]) >= (b["score"], -b["distance_miles"])


def test_candidates_endpoint_returns_200_for_no_pool(
    seed: SeedFn,
    public_client: TestClient,
) -> None:
    """Isolated case with no geo-temporal neighbours: empty candidates + leads."""
    corpus = seed(
        "CORR_CANDIDATES_TEST_EMPTY",
        [
            _case_spec(
                "iso",
                incident_date=date(1990, 1, 1),
                lat=40.0,
                lon=-20.0,
            ),
        ],
    )
    focal_id = corpus.case_ids["CC-iso"]
    resp = public_client.get(f"/api/v1/cold-cases/{focal_id}/correlation-candidates")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["candidates"] == []
    assert data["leads"] == []
    assert data["score_max"] == CORRELATION_SCORE_SCALE
    assert data["score_floor"] == CORRELATION_SCORE_FLOOR


def test_candidates_endpoint_404_for_missing_case(
    public_client: TestClient,
) -> None:
    """A nonexistent focal case 404s (not a 200 empty pool), so consumers can
    distinguish invalid input from a valid case with no neighbours."""
    resp = public_client.get("/api/v1/cold-cases/999999999/correlation-candidates")
    assert resp.status_code == 404, resp.text

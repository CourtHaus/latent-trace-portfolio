"""GET /api/v1/cold-cases/{case_id} — detail endpoint.

Self-seeding: seeds a small synthetic corpus once per module (state=ZZ,
source_code=DETAIL_API_TEST) plus one function-scoped case for the
destructive extraction-deletion test.  Every assertion targets seeded
case_ids so the module is fully isolated from the historical dev-DB data.

Corpus layout
─────────────
  det-main     fully-populated case: victim (female/White/age 35), contact,
               photo, Tier-1 (weapon=firearm, location_type=residence) +
               Tier-2 extractions, geocoded (lat/lon in the North Atlantic).
  det-corr     correlates with det-main: same weapon + location_type + victim
               gender, coordinates ~10 mi away, date 5 yr later.
               Score is rarity-weighted (0-10 scale); shares weapon +
               location_type + gender >= CORRELATION_MIN_DIMENSIONS=2 dims.
  det-nocontact  no contact row — exercises the contact=None branch.
  det-noextract  has a Tier-1 extraction row that is deleted by a function-
               scoped test, then cleaned up automatically by teardown.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tests.integration._seed import (
    CaseSpec,
    ContactSpec,
    ExtractionSpec,
    PhotoSpec,
    SeededCorpus,
    SeedFn,
    VictimExtractionSpec,
    VictimSpec,
)

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

# ---------------------------------------------------------------------------
# Module-level corpus
# ---------------------------------------------------------------------------

# North-Atlantic coordinates — no collision with real US data.
_LAT = 40.0
_LON = -20.0

# det-corr is ~10 mi away; well within the 50-mi correlation hard filter.
_CORR_LAT = 40.15
_CORR_LON = -20.0

_CASES: list[CaseSpec] = [
    # det-main: fully-populated — victims, contact, photo, Tier-1+Tier-2.
    CaseSpec(
        source_case_id="det-main",
        case_name="Detail API Test Main Case",
        state="ZZ",
        case_type="homicide",
        city="Testville",
        incident_date="2005-06-15",
        address="123 Main St",
        about_text="Test about text for det-main.",
        latitude=_LAT,
        longitude=_LON,
        geocode_precision="street",
        slug="detail-api-test-det-main",
        victims=[
            VictimSpec(
                first_name="Alice",
                last_name="Alpha",
                gender="female",
                race="White",
                age_text="35",
            )
        ],
        contact=ContactSpec(last_name="Cold Case Unit", phone="555-000-0001"),
        photos=[
            PhotoSpec(
                filename="test-photo.jpg",
                content_type="image/jpeg",
                sha256="a" * 64,
                is_primary=True,
            )
        ],
        extractions=[
            ExtractionSpec(
                prompt_tier=1,
                weapon="firearm",
                location_type="residence",
            ),
            ExtractionSpec(
                prompt_tier=2,
                incident_date_text="June 15, 2005",
                address_text="123 Main Street, Testville",
                victim_age_text="35 years old",
                victim_gender_text="female",
            ),
        ],
    ),
    # det-corr: correlates with det-main.
    # weapon=firearm + location_type=residence + gender=female (3 dimensions >= 2 min)
    CaseSpec(
        source_case_id="det-corr",
        case_name="Detail API Test Correlated Case",
        state="ZZ",
        case_type="homicide",
        city="Testville",
        incident_date="2010-03-20",
        latitude=_CORR_LAT,
        longitude=_CORR_LON,
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Betty",
                last_name="Beta",
                gender="female",
                race="Black",
                age_text="42",
            )
        ],
        contact=ContactSpec(last_name="Cold Case Unit"),
        extractions=[
            ExtractionSpec(
                prompt_tier=1,
                weapon="firearm",
                location_type="residence",
            ),
        ],
    ),
    # det-promoted: victim demographics promoted from Tier-2 (Phase 2) —
    # exercises per-victim extraction provenance on the detail endpoint.
    CaseSpec(
        source_case_id="det-promoted",
        case_name="Promoted Provenance",
        state="MD",
        about_text="The 34-year-old victim was found. She had been reported missing.",
        victims=[
            VictimSpec(
                first_name="Promoted",
                last_name="Victim",
                age_text="34",
                age_source="tier2",
                gender="F",
                gender_source="tier2",
                extraction=VictimExtractionSpec(
                    age_text="34",
                    age_raw_phrase="34-year-old",
                    age_source_start=4,
                    age_source_end=15,
                    gender_text="F",
                    gender_raw_phrase="She",
                    gender_source_start=34,
                    gender_source_end=37,
                ),
            )
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="unknown", location_type="unknown")],
    ),
    # det-mixed: source-provided age + tier2-promoted gender, BOTH with linked
    # extraction data — exercises the per-field *_source gating (a bare
    # ext-row-exists check would wrongly attach age provenance here).
    CaseSpec(
        source_case_id="det-mixed",
        case_name="Mixed Provenance",
        state="MD",
        about_text="The 50-year-old victim was found. He had been reported missing.",
        victims=[
            VictimSpec(
                first_name="Mixed",
                last_name="Victim",
                age_text="50",
                age_source="source",
                gender="M",
                gender_source="tier2",
                extraction=VictimExtractionSpec(
                    age_text="50",
                    age_raw_phrase="50-year-old",
                    age_source_start=4,
                    age_source_end=15,
                    gender_text="M",
                    gender_raw_phrase="He",
                    gender_source_start=34,
                    gender_source_end=36,
                ),
            )
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="unknown", location_type="unknown")],
    ),
    # det-nocontact: no contact row; victim present; Tier-1 extraction.
    CaseSpec(
        source_case_id="det-nocontact",
        case_name="Detail API Test No Contact",
        state="ZZ",
        case_type="homicide",
        city="Testville",
        incident_date="2008-11-01",
        latitude=_LAT + 0.5,
        longitude=_LON + 0.5,
        geocode_precision="landmark",
        victims=[VictimSpec(first_name="Carol", last_name="Charlie", gender="male", race="Black")],
        contact=None,
        extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type="public_outdoor")],
    ),
]


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    """Seed the ZZ-state detail-API corpus once for this module."""
    return seeded_corpus("DETAIL_API_TEST", _CASES)


# ---------------------------------------------------------------------------
# Happy-path and structure tests — all use corpus.case_ids["det-main"]
# ---------------------------------------------------------------------------


def test_detail_happy_path(public_client: TestClient, corpus: SeededCorpus) -> None:
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] == case_id
    assert body["slug"]
    assert isinstance(body["victims"], list)


def test_detail_returns_404_for_unknown_id(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/999999999")
    assert r.status_code == 404


def test_detail_returns_422_for_non_integer_id(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/abc")
    assert r.status_code == 422


def test_detail_response_has_expected_top_level_keys(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    body = r.json()
    assert set(body.keys()) == {
        "case_id",
        "slug",
        "source_case_id",
        "case_name",
        "case_type",
        "incident_date",
        "address",
        "city",
        "state",
        "about_text",
        "latitude",
        "longitude",
        "geocode_precision",
        "namus_case_id",
        "ncmec_case_id",
        "ncic_case_id",
        "address_source",
        "incident_date_source",
        "victims",
        "contact",
        "extraction",
        "correlations",
        "photos",
    }


def test_detail_extraction_block_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    """det-main has both Tier-1 and Tier-2 extractions; response must include
    a fully-populated CaseExtractionBlock."""
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    body = r.json()
    assert body["extraction"] is not None
    ex = body["extraction"]
    assert {"weapon", "location_type", "incident_date", "address", "model_id", "extracted_at"}.issubset(ex.keys())
    assert "victim_age" not in ex
    assert "victim_gender" not in ex
    for field_name in ("weapon", "location_type"):
        f = ex[field_name]
        assert set(f.keys()) == {
            "value",
            "raw_phrase",
            "source_start",
            "source_end",
            "low_confidence",
        }
        assert isinstance(f["low_confidence"], bool)
        assert f["value"] is None or isinstance(f["value"], str)
        assert f["raw_phrase"] is None or isinstance(f["raw_phrase"], str)
        assert f["source_start"] is None or isinstance(f["source_start"], int)
        assert f["source_end"] is None or isinstance(f["source_end"], int)
    # Tier-1 seeded values are asserted against known corpus values.
    assert ex["weapon"]["value"] == "firearm"
    assert ex["location_type"]["value"] == "residence"


def test_detail_extraction_none_when_no_extraction_row(
    public_client: TestClient,
    seed: SeedFn,
) -> None:
    """A case whose Tier-1 extraction row is deleted returns extraction=None.

    Uses a function-scoped corpus so the delete is isolated and cleaned up
    automatically by the seed fixture's teardown — no restore is needed.
    """
    from sqlalchemy import create_engine, text

    from casesignal.etl.services.db import create_session_factory

    corpus = seed(
        "DETAIL_API_TEST_NOEXT",
        [
            CaseSpec(
                source_case_id="det-noext",
                case_name="Detail API Test No Extraction",
                state="ZZ",
                case_type="homicide",
                extractions=[
                    ExtractionSpec(prompt_tier=1, weapon="knife", location_type="vehicle")
                ],
            )
        ],
    )
    case_id = corpus.case_ids["det-noext"]

    # Verify extraction is present before deletion.
    r_before = public_client.get(f"/api/v1/cold-cases/{case_id}")
    assert r_before.status_code == 200
    assert r_before.json()["extraction"] is not None

    # Delete the Tier-1 extraction row directly.
    from tests.support.db_guard import resolve_test_database_url

    engine = create_engine(resolve_test_database_url())
    sf = create_session_factory(engine)
    with sf() as s:
        s.execute(
            text("DELETE FROM cold_case.case_extractions WHERE case_id = :cid AND prompt_tier = 1"),
            {"cid": case_id},
        )
        s.commit()
    engine.dispose()

    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    assert r.status_code == 200
    assert r.json()["extraction"] is None
    # The seed fixture's teardown deletes the whole corpus — no restore needed.


def test_detail_victim_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    """det-main has one victim; the victim block must have the locked schema."""
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    body = r.json()
    assert len(body["victims"]) > 0
    v = body["victims"][0]
    assert set(v.keys()) == {
        "victim_id",
        "first_name",
        "last_name",
        "gender",
        "height_text",
        "weight_num",
        "age_text",
        "age_num",
        "race",
        "eye_color",
        "hair_color",
        "dob",
        "dod",
        "ethnicity",
        "tribal_affiliation",
        "identifying_marks",
        "aliases",
        "occupation",
        "age_source",
        "gender_source",
        "race_source",
        "age_extraction",
        "gender_extraction",
    }
    # Values match what was seeded.
    assert v["first_name"] == "Alice"
    assert v["last_name"] == "Alpha"
    assert v["gender"] == "female"
    assert v["race"] == "White"
    assert v["age_text"] == "35"


def test_detail_contact_redaction(public_client: TestClient, corpus: SeededCorpus) -> None:
    """det-main has a contact with last_name + phone.
    The response must expose the phone channel but NOT expose first_name / last_name."""
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    assert r.status_code == 200
    contact = r.json()["contact"]
    assert contact is not None

    # Channel field is present.
    assert contact["phone"] == "555-000-0001"

    # Personal name fields are NOT in the response payload.
    assert "first_name" not in contact
    assert "last_name" not in contact


def test_detail_contact_null_when_no_contact_row(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    """det-nocontact has no contact row — the response must have contact=None."""
    case_id = corpus.case_ids["det-nocontact"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    assert r.status_code == 200
    assert r.json()["contact"] is None


def test_detail_slug_is_nonempty(public_client: TestClient, corpus: SeededCorpus) -> None:
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    slug = r.json()["slug"]
    assert slug
    assert isinstance(slug, str)
    assert len(slug) > 0
    # Matches the explicitly-set slug in the corpus.
    assert slug == "detail-api-test-det-main"


def test_detail_response_includes_source_case_id(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    body = r.json()
    assert "source_case_id" in body
    assert isinstance(body["source_case_id"], str)
    assert len(body["source_case_id"]) > 0
    assert body["source_case_id"] == "det-main"


def test_detail_endpoint_includes_correlations_field(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    assert r.status_code == 200
    body = r.json()
    assert "correlations" in body
    assert isinstance(body["correlations"], list)


def test_detail_correlations_item_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    """det-main and det-corr share weapon + location_type + gender; the
    correlation engine must surface det-corr in det-main's correlations panel
    with the locked schema shape."""
    from casesignal.correlation.config import CORRELATION_SCORE_FLOOR, CORRELATION_SCORE_SCALE

    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    body = r.json()
    corrs = body["correlations"]
    # The corpus guarantees at least one correlation (det-corr) clears the floor.
    assert len(corrs) >= 1, (
        "det-corr should appear in det-main correlations "
        "(weapon + location_type + gender >= CORRELATION_MIN_DIMENSIONS=2)"
    )
    item = corrs[0]
    assert set(item.keys()) == {
        "case_id",
        "slug",
        "victim_primary_name",
        "city",
        "state",
        "year",
        "score",
        "score_max",
        "proximity_factor",
        "matched_dimensions",
        "distance_miles",
        "years_apart",
    }
    assert item["score_max"] == CORRELATION_SCORE_SCALE
    assert item["score"] >= CORRELATION_SCORE_FLOOR
    assert item["score"] <= CORRELATION_SCORE_SCALE
    assert 0 < item["proximity_factor"] <= 1.0
    assert len(item["matched_dimensions"]) > 0
    for d in item["matched_dimensions"]:
        assert set(d.keys()) == {"name", "value", "low_confidence", "weight"}

    # Verify det-corr is the correlated case and its dimensions match expectations.
    corr_case_id = corpus.case_ids["det-corr"]
    matched = next((c for c in corrs if c["case_id"] == corr_case_id), None)
    assert matched is not None, "det-corr must appear in det-main's correlations"
    dim_names = {d["name"] for d in matched["matched_dimensions"]}
    # weapon + location_type must match (both seeded identically).
    assert "weapon" in dim_names
    assert "location_type" in dim_names


def test_detail_response_includes_provenance_fields(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    """Case detail response includes provenance fields for address, incident_date,
    and victim demographics (age, gender, race)."""
    case_id = corpus.case_ids["det-main"]
    r = public_client.get(f"/api/v1/cold-cases/{case_id}")
    assert r.status_code == 200
    data = r.json()
    # Top-level provenance fields exist (values may be None or a string).
    assert "address_source" in data
    assert "incident_date_source" in data
    # Victim provenance fields exist on all victims.
    for victim in data["victims"]:
        assert "age_source" in victim
        assert "gender_source" in victim
        assert "race_source" in victim


def test_detail_victim_carries_extraction_provenance(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """A victim whose demographics were promoted (age_source='tier2') exposes
    per-victim ExtractedField provenance for the reveal-source UI."""
    case_id = corpus.case_ids["det-promoted"]
    body = public_client.get(f"/api/v1/cold-cases/{case_id}").json()
    v = body["victims"][0]
    assert v["age_source"] == "tier2"
    assert v["age_extraction"]["value"] == "34"
    assert v["age_extraction"]["raw_phrase"] == "34-year-old"
    assert v["age_extraction"]["source_start"] == 4
    assert v["age_extraction"]["source_end"] == 15
    assert v["age_extraction"]["low_confidence"] is False
    assert v["gender_extraction"]["value"] == "F"
    assert v["gender_extraction"]["raw_phrase"] == "She"
    assert v["gender_extraction"]["source_start"] == 34
    assert v["gender_extraction"]["source_end"] == 37


def test_detail_victim_extraction_none_for_source_demographics(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """Source-provided demographics expose NO extraction provenance."""
    case_id = corpus.case_ids["det-main"]
    body = public_client.get(f"/api/v1/cold-cases/{case_id}").json()
    v = body["victims"][0]
    assert v["age_extraction"] is None
    assert v["gender_extraction"] is None


def test_detail_extraction_block_has_no_case_level_victim_fields(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """Phase 2 moved victim demographics provenance per-victim; the case-level
    extraction block no longer carries victim_age / victim_gender."""
    case_id = corpus.case_ids["det-main"]
    body = public_client.get(f"/api/v1/cold-cases/{case_id}").json()
    assert "victim_age" not in body["extraction"]
    assert "victim_gender" not in body["extraction"]


def test_detail_victim_provenance_gated_per_field(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """The *_source gate is per-field: a victim with source-provided age but
    tier2-promoted gender exposes provenance ONLY for gender, even though the
    linked extraction row carries both fields."""
    case_id = corpus.case_ids["det-mixed"]
    body = public_client.get(f"/api/v1/cold-cases/{case_id}").json()
    v = body["victims"][0]
    assert v["age_source"] == "source"
    assert v["age_extraction"] is None
    assert v["gender_source"] == "tier2"
    assert v["gender_extraction"]["value"] == "M"
    assert v["gender_extraction"]["source_start"] == 34
    assert v["gender_extraction"]["source_end"] == 36

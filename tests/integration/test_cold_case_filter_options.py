"""GET /api/v1/cold-cases/filter-options - dataset distinct values for filter UIs.

Self-seeding: this endpoint intentionally DISTINCTs the whole corpus, so tests
seed distinctive values and assert presence/subset behavior instead of exact
global equality.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.integration._seed import CaseSpec, ExtractionSpec, SeededCorpus, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_SOURCE_CODE = "FILTER_OPTS_TEST"

_CASES: list[CaseSpec] = [
    CaseSpec(
        source_case_id="fopt-01",
        case_name="Filter Options Test Firearm",
        state="ZZ",
        case_type="homicide",
        city="Filteropolis",
        incident_date="1991-01-02",
        victims=[
            VictimSpec(
                first_name="Fiona",
                last_name="Filter",
                gender="female",
                race="Black",
            )
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
    ),
    CaseSpec(
        source_case_id="fopt-02",
        case_name="Filter Options Test Knife",
        state="ZZ",
        case_type="suspicious_death",
        city="Zephyrville",
        incident_date="2002-03-04",
        victims=[
            VictimSpec(
                first_name="Mark",
                last_name="Filter",
                gender="male",
                # A different source spelling of the same concept — must fold
                # into the single "Black or African American" canonical bucket.
                race="BLACK or AFRICAN AMERICAN",
            )
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type="vehicle")],
    ),
    CaseSpec(
        source_case_id="fopt-03",
        case_name="Filter Options Test Unknown",
        state="ZZ",
        case_type="homicide",
        city="Filteropolis",
        incident_date="2010-05-06",
        victims=[
            VictimSpec(
                first_name="Una",
                last_name="Unknown",
                gender="unknown",
                race="White",
            )
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="unknown", location_type="unknown")],
    ),
    CaseSpec(
        source_case_id="fopt-04",
        case_name="Filter Options Test Null Extraction",
        state="ZZ",
        case_type="missing_person",
        city="Nulltown",
        incident_date="2005-07-08",
        victims=[],
        extractions=[ExtractionSpec(prompt_tier=1, weapon=None, location_type=None)],
    ),
]


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    return seeded_corpus(_SOURCE_CODE, _CASES)


def _body(public_client: TestClient, corpus: SeededCorpus) -> dict[str, Any]:
    r = public_client.get("/api/v1/cold-cases/filter-options")
    assert r.status_code == 200
    return cast(dict[str, Any], r.json())


def test_filter_options_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert set(body.keys()) == {
        "case_types",
        "cities",
        "genders",
        "races",
        "states",
        "weapons",
        "location_types",
        "source_systems",
        "year_range",
        "dataset",
    }
    assert isinstance(body["case_types"], list)
    assert isinstance(body["cities"], list)
    assert isinstance(body["genders"], list)
    assert isinstance(body["races"], list)
    assert isinstance(body["states"], list)
    assert isinstance(body["weapons"], list)
    assert isinstance(body["location_types"], list)
    assert isinstance(body["source_systems"], list)
    assert isinstance(body["year_range"], dict)
    assert set(body["year_range"].keys()) == {"min", "max"}


def test_filter_options_include_seeded_values(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert {"homicide", "suspicious_death", "missing_person"} <= set(body["case_types"])
    assert {"Filteropolis", "Zephyrville", "Nulltown"} <= set(body["cities"])
    assert "ZZ" in body["states"]
    assert {"F", "M", "unknown"} <= set(body["genders"])
    # Races are exposed as canonical NIBRS buckets, not raw source spellings.
    assert {"Black or African American", "White"} <= set(body["races"])
    assert {"firearm", "knife", "unknown"} <= set(body["weapons"])
    assert {"residence", "vehicle", "unknown"} <= set(body["location_types"])
    assert any(source["code"] == _SOURCE_CODE for source in body["source_systems"])
    assert body["year_range"]["min"] <= 1991
    assert body["year_range"]["max"] >= 2010


def test_filter_options_arrays_sorted_alphabetical_case_insensitive(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    body = _body(public_client, corpus)
    for key in ("case_types", "cities", "genders", "races", "states"):
        arr = body[key]
        assert arr == sorted(arr, key=str.lower), f"{key} not alphabetically sorted"


def test_filter_options_cache_control_header(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/filter-options")
    assert r.status_code == 200
    cache = r.headers.get("cache-control", "")
    assert "max-age=3600" in cache
    assert "stale-while-revalidate=86400" in cache


def test_filter_options_weapons_and_location_types_exclude_null(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    body = _body(public_client, corpus)
    assert "" not in body["weapons"]
    assert "" not in body["location_types"]
    assert None not in body["weapons"]
    assert None not in body["location_types"]


def test_filter_options_weapons_and_location_types_sorted_alphabetical(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    body = _body(public_client, corpus)
    assert body["weapons"] == sorted(body["weapons"])
    assert body["location_types"] == sorted(body["location_types"])


def test_filter_options_includes_dataset_block(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert "dataset" in body
    assert set(body["dataset"].keys()) == {"version", "last_ingested"}
    assert isinstance(body["dataset"]["version"], str)
    assert body["dataset"]["version"] != ""
    last_ingested = body["dataset"]["last_ingested"]
    assert last_ingested is None or isinstance(last_ingested, str)


def test_filter_options_race_canonical_bucketing(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    races = _body(public_client, corpus)["races"]
    # The two seeded spellings ("Black" + "BLACK or AFRICAN AMERICAN") collapse
    # to exactly one canonical bucket — no raw source spelling leaks through.
    assert races.count("Black or African American") == 1
    assert "Black" not in races
    assert "BLACK or AFRICAN AMERICAN" not in races
    assert "filterrace" not in {r.lower() for r in races}


def test_filter_options_gender_canonical_only(public_client: TestClient, corpus: SeededCorpus) -> None:
    genders = _body(public_client, corpus)["genders"]
    assert set(genders) <= {"M", "F", "unknown"}, genders
    assert {"M", "F", "unknown"} <= set(genders)

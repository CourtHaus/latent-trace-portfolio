"""GET /api/v1/cold-cases/facet-counts — unscoped per-facet case counts.

Like filter-options, this counts the whole corpus, so we seed a distinctive
state ("QQ") to assert exact contribution and use subset/presence for facets
that share values with real data.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.integration._seed import (
    CaseSpec,
    ExtractionSpec,
    SeededCorpus,
    SeedFn,
    VictimSpec,
)

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_SOURCE_CODE = "FACET_COUNTS_TEST"

_CASES: list[CaseSpec] = [
    CaseSpec(
        source_case_id="fc-01",
        case_name="Facet Counts One",
        state="QQ",
        case_type="homicide",
        incident_date="1990-01-01",
        latitude=27.0,
        longitude=-80.0,
        geocode_precision="street",
        victims=[
            VictimSpec(first_name="Faye", last_name="Count", gender="female", race="White")
        ],
        extractions=[
            ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")
        ],
    ),
    CaseSpec(
        source_case_id="fc-02",
        case_name="Facet Counts Two",
        state="QQ",
        case_type="homicide",
        incident_date="1991-01-01",
        latitude=27.1,
        longitude=-80.1,
        geocode_precision="street",
        victims=[
            VictimSpec(first_name="Max", last_name="Count", gender="male", race="Black")
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm")],
    ),
    CaseSpec(
        source_case_id="fc-03",
        case_name="Facet Counts Three",
        state="QQ",
        case_type="missing_person",
        incident_date="1992-01-01",
        victims=[
            # A different source spelling of White — folds into the same canonical
            # bucket as fc-01's "White", so the race facet counts both as one.
            VictimSpec(first_name="Faye", last_name="Count", gender="female", race="Caucasian")
        ],
        extractions=[ExtractionSpec(prompt_tier=1, location_type="residence")],
    ),
]


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    return seeded_corpus(_SOURCE_CODE, _CASES)


def _body(public_client: TestClient, corpus: SeededCorpus) -> dict[str, Any]:
    r = public_client.get("/api/v1/cold-cases/facet-counts")
    assert r.status_code == 200
    return cast(dict[str, Any], r.json())


def _facet(body: dict[str, Any], key: str) -> dict[str, int]:
    return {row["value"]: row["count"] for row in body[key]}


_FACET_KEYS = (
    "case_type",
    "state",
    "gender",
    "race",
    "precision",
    "weapon",
    "location_type",
    "source_system",
)


def test_facet_counts_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert set(body.keys()) == {*_FACET_KEYS, "geocoded", "total"}
    for key in _FACET_KEYS:
        assert isinstance(body[key], list)
        for row in body[key]:
            assert set(row.keys()) == {"value", "count"}
            assert isinstance(row["value"], str)
            assert isinstance(row["count"], int)
    assert isinstance(body["geocoded"], int)
    assert isinstance(body["total"], int)


def test_state_facet_exact_for_distinctive_state(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    body = _body(public_client, corpus)
    assert _facet(body, "state").get("QQ") == 3


def test_geocoded_and_total_scalars(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    # Two of the three seeded cases carry coordinates.
    assert body["geocoded"] >= 2
    assert body["total"] >= 3
    assert body["total"] >= body["geocoded"]


def test_precision_and_type_and_gender_present(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    body = _body(public_client, corpus)
    assert _facet(body, "precision").get("street", 0) >= 2
    assert _facet(body, "case_type").get("homicide", 0) >= 2
    gender = _facet(body, "gender")
    assert gender.get("F", 0) >= 2
    assert gender.get("M", 0) >= 1


def test_source_system_facet_exact_for_seeded_source(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    # source_system is keyed by source_code; the test source code is unique.
    assert _facet(_body(public_client, corpus), "source_system").get(_SOURCE_CODE) == 3


def test_race_weapon_location_facets_present(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    body = _body(public_client, corpus)
    # Shared with real corpus values → subset/presence, not exact. Races are
    # canonical NIBRS buckets: "White" + "Caucasian" both fold to "White" (>=2),
    # and "Black" folds to "Black or African American".
    assert _facet(body, "race").get("White", 0) >= 2
    assert _facet(body, "race").get("Black or African American", 0) >= 1
    assert _facet(body, "weapon").get("firearm", 0) >= 2
    assert _facet(body, "location_type").get("residence", 0) >= 2


def test_counts_scoped_by_other_filter(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    # Filtering to the distinctive QQ state isolates exactly the 3 seeded cases,
    # so other facets become exact for them.
    r = public_client.get("/api/v1/cold-cases/facet-counts?state=QQ")
    assert r.status_code == 200
    body = cast(dict[str, Any], r.json())
    assert body["total"] == 3
    assert _facet(body, "case_type") == {"homicide": 2, "missing_person": 1}
    assert _facet(body, "gender") == {"F": 2, "M": 1}
    # source_system scoped to QQ → only the seeded source contributes.
    assert _facet(body, "source_system") == {_SOURCE_CODE: 3}


def test_facet_excludes_its_own_selection(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    # With state=QQ AND case_type=homicide, total reflects both filters (2 cases),
    # but the case_type facet itself ignores case_type — it still surfaces
    # missing_person=1 so the user can see what switching would yield. gender,
    # however, IS scoped by case_type=homicide.
    r = public_client.get("/api/v1/cold-cases/facet-counts?state=QQ&case_type=homicide")
    assert r.status_code == 200
    body = cast(dict[str, Any], r.json())
    assert body["total"] == 2
    assert _facet(body, "case_type") == {"homicide": 2, "missing_person": 1}
    assert _facet(body, "gender") == {"F": 1, "M": 1}


def test_facets_sorted_by_count_desc(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    for key in _FACET_KEYS:
        counts = [row["count"] for row in body[key]]
        assert counts == sorted(counts, reverse=True), f"{key} not count-desc"


def test_facet_counts_cache_header(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/facet-counts")
    cache = r.headers.get("cache-control", "")
    assert "max-age=3600" in cache
    assert "stale-while-revalidate=86400" in cache

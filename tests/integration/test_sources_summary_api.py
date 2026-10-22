"""GET /api/v1/cold-cases/sources-summary - per-source aggregates.

Self-seeding: the endpoint is global, so tests find the seeded source row and
assert exact aggregates for that row while keeping global ordering/invariant
checks across the whole response.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.integration._seed import CaseSpec, SeededCorpus, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_SOURCE_CODE = "SOURCES_SUMMARY_TEST"

_CASES: list[CaseSpec] = [
    CaseSpec(
        source_case_id="ssum-01",
        case_name="Sources Summary Test Geocoded 1990",
        state="ZZ",
        city="Summaryville",
        incident_date="1990-01-02",
        latitude=40.0,
        longitude=-20.0,
        victims=[VictimSpec(first_name="Source", last_name="One")],
    ),
    CaseSpec(
        source_case_id="ssum-02",
        case_name="Sources Summary Test Ungeocoded 2005",
        state="ZZ",
        city="Summaryville",
        incident_date="2005-03-04",
        victims=[VictimSpec(first_name="Source", last_name="Two")],
    ),
    CaseSpec(
        source_case_id="ssum-03",
        case_name="Sources Summary Test Geocoded 2015",
        state="ZZ",
        city="Summaryville",
        incident_date="2015-05-06",
        latitude=40.01,
        longitude=-20.01,
        victims=[VictimSpec(first_name="Source", last_name="Three")],
    ),
]


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    return seeded_corpus(_SOURCE_CODE, _CASES, source_state="ZZ")


def _body(public_client: TestClient, corpus: SeededCorpus) -> dict[str, Any]:
    r = public_client.get("/api/v1/cold-cases/sources-summary")
    assert r.status_code == 200
    return cast(dict[str, Any], r.json())


def _seeded_row(body: dict[str, Any]) -> dict[str, Any]:
    row = next((item for item in body["data"] if item["code"] == _SOURCE_CODE), None)
    assert row is not None
    return cast(dict[str, Any], row)


def test_sources_summary_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert "data" in body
    assert isinstance(body["data"], list)
    assert body["data"]
    item = body["data"][0]
    assert set(item.keys()) == {
        "code",
        "name",
        "state",
        "case_count",
        "geocoded_count",
        "year_min",
        "year_max",
    }


def test_sources_summary_seeded_source_has_exact_counts(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    row = _seeded_row(_body(public_client, corpus))
    assert row["name"] == f"{_SOURCE_CODE} (integration-test seed)"
    assert row["state"] == "ZZ"
    assert row["case_count"] == 3
    assert row["geocoded_count"] == 2
    assert row["year_min"] == 1990
    assert row["year_max"] == 2015


def test_sources_summary_ordered_by_case_count_desc(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    body = _body(public_client, corpus)
    counts = [row["case_count"] for row in body["data"]]
    assert counts == sorted(counts, reverse=True)


def test_sources_summary_geocoded_does_not_exceed_total(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    body = _body(public_client, corpus)
    for row in body["data"]:
        assert row["geocoded_count"] <= row["case_count"], row["code"]


def test_sources_summary_cache_control_set(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/sources-summary")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "max-age=3600" in cc
    assert "stale-while-revalidate=86400" in cc

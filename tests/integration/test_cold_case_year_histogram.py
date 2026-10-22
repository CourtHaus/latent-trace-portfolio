"""GET /api/v1/cold-cases/year-histogram — per-year incident counts.

Counts the whole corpus, so we assert presence of seeded years + structural
invariants rather than exact global bucket counts.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.integration._seed import CaseSpec, SeededCorpus, SeedFn

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_SOURCE_CODE = "YEAR_HIST_TEST"

_CASES: list[CaseSpec] = [
    CaseSpec(source_case_id="yh-01", case_name="Year Hist 1969", state="QR", incident_date="1969-06-01"),
    CaseSpec(source_case_id="yh-02", case_name="Year Hist 1988", state="QR", incident_date="1988-06-01"),
    CaseSpec(source_case_id="yh-03", case_name="Year Hist 2001", state="QR", incident_date="2001-06-01"),
    CaseSpec(source_case_id="yh-04", case_name="Year Hist Undated", state="QR", incident_date=None),
]


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    return seeded_corpus(_SOURCE_CODE, _CASES)


def _body(public_client: TestClient, corpus: SeededCorpus) -> dict[str, Any]:
    r = public_client.get("/api/v1/cold-cases/year-histogram")
    assert r.status_code == 200
    return cast(dict[str, Any], r.json())


def test_year_histogram_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert set(body.keys()) == {"buckets", "total_dated", "undated"}
    assert isinstance(body["buckets"], list)
    for row in body["buckets"]:
        assert set(row.keys()) == {"year", "count"}
        assert isinstance(row["year"], int)
        assert isinstance(row["count"], int)
        assert row["count"] > 0


def test_buckets_sorted_ascending(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    years = [row["year"] for row in body["buckets"]]
    assert years == sorted(years)


def test_seeded_years_present(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    years = {row["year"] for row in body["buckets"]}
    assert {1969, 1988, 2001} <= years


def test_total_dated_matches_bucket_sum(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert body["total_dated"] == sum(row["count"] for row in body["buckets"])
    assert body["total_dated"] >= 3


def test_undated_counts_seeded_null(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert body["undated"] >= 1


def test_year_histogram_cache_header(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/year-histogram")
    cache = r.headers.get("cache-control", "")
    assert "max-age=3600" in cache
    assert "stale-while-revalidate=86400" in cache

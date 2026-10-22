from __future__ import annotations

import os
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.integration._seed import CaseSpec, SeededCorpus, SeedFn

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_SOURCE_CODE = "COV_HIST_TEST"
_CASES: list[CaseSpec] = [
    CaseSpec(source_case_id="cov-01", case_name="Cov 1991", state="ZZ", incident_date="1991-03-01"),
    CaseSpec(source_case_id="cov-02", case_name="Cov 1995", state="ZZ", incident_date="1995-03-01"),
    CaseSpec(source_case_id="cov-03", case_name="Cov 2003", state="ZZ", incident_date="2003-03-01"),
    CaseSpec(source_case_id="cov-04", case_name="Cov Undated", state="ZZ", incident_date=None),
]


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    return seeded_corpus(_SOURCE_CODE, _CASES, source_state="ZZ")


def _body(public_client: TestClient, corpus: SeededCorpus) -> dict[str, Any]:
    r = public_client.get("/api/v1/cold-cases/coverage-histogram")
    assert r.status_code == 200
    return cast(dict[str, Any], r.json())


def test_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    assert set(body.keys()) == {"buckets"}
    for row in body["buckets"]:
        assert set(row.keys()) == {"state", "decade", "count"}
        assert isinstance(row["decade"], int) and row["decade"] % 10 == 0
        assert row["count"] > 0


def test_groups_seeded_state_by_decade(public_client: TestClient, corpus: SeededCorpus) -> None:
    body = _body(public_client, corpus)
    zz = {b["decade"]: b["count"] for b in body["buckets"] if b["state"] == "ZZ"}
    assert zz.get(1990) == 2
    assert zz.get(2000) == 1
    assert 1980 not in zz


# TODO(phase-2-followup): add archived-exclusion test (see year-histogram, same gap)

"""The list + map endpoints must advertise a cacheable Cache-Control so
Vercel's Data Cache (and any browser/CDN) can absorb read spikes. The other
read endpoints already do this; these two were the gap (see the demo-hardening
spec). Header is set unconditionally, so no seeding is needed."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from casesignal.api.app import create_app

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

EXPECTED = "max-age=3600, stale-while-revalidate=86400"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_list_endpoint_sets_cache_control(client: TestClient) -> None:
    resp = client.get("/api/v1/cold-cases?limit=1")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == EXPECTED


def test_map_endpoint_sets_cache_control(client: TestClient) -> None:
    resp = client.get("/api/v1/cold-cases/map?limit=1")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == EXPECTED


def test_map_clusters_path_sets_cache_control(client: TestClient) -> None:
    # zoom=0 is always below CLUSTER_ZOOM_THRESHOLD, so this exercises the
    # clusters return path (the points path is covered by the test above).
    resp = client.get("/api/v1/cold-cases/map?zoom=0&limit=1")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == EXPECTED

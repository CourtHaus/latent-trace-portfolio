"""Regression fence: every public route in the A0 ledger must respond to an
anonymous request without 401. Guards against a future developer accidentally
re-adding a router-level require_api_key dependency."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


# (path, method) — expected: not 401. 200/404/422 are all fine; the point is
# that the route isn't rejecting the anonymous request at auth time.
PUBLIC_ROUTES = [
    ("/healthz", "GET"),
    ("/api/v1/cold-cases", "GET"),
    ("/api/v1/cold-cases/map?bbox=-180,-90,180,90", "GET"),
    ("/api/v1/cold-cases/filter-options", "GET"),
    ("/api/v1/cold-cases/facet-counts", "GET"),
    ("/api/v1/cold-cases/year-histogram", "GET"),
    ("/api/v1/cold-cases/coverage-histogram", "GET"),
    ("/api/v1/cold-cases/1", "GET"),
    ("/api/v1/cold-cases/1/correlation-candidates", "GET"),
    ("/api/v1/cold-cases/1/photos/nonexistent.jpg", "GET"),
]


@pytest.mark.parametrize("path, method", PUBLIC_ROUTES)
def test_public_route_is_not_401(public_client: TestClient, path: str, method: str) -> None:
    resp = public_client.request(method, path)
    assert resp.status_code != 401, (
        f"{method} {path} returned 401 without auth — a router-level "
        f"require_api_key may have been re-added. Response body: {resp.text[:200]}"
    )

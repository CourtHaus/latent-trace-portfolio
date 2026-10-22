"""Undecorated routes are covered by the global default limit (SEC-B01).

The limiter is created with default_limits=["120/minute"], but those limits
only take effect when SlowAPIMiddleware is registered. Without it, every route
that lacks an explicit @limiter.limit decorator (all of /admin, /operator,
/methodology, /healthz) has NO rate limit at all. This test pins the
middleware in place by exercising an undecorated, DB-free, auth-free route.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from casesignal.api.app import create_app

pytestmark = pytest.mark.integration

_DEFAULT_LIMIT_PER_MINUTE = 120  # matches Limiter(default_limits=["120/minute"])


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Any:
    from casesignal.api.middleware.rate_limit import limiter

    assert hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"), (
        "slowapi internal API changed — limiter._storage.reset() no longer "
        "available. Find the new reset path before relying on this fixture."
    )
    limiter._storage.reset()
    yield
    limiter._storage.reset()


def test_undecorated_route_enforces_default_limit() -> None:
    app = create_app()
    with TestClient(app) as client:
        last_status = None
        for _ in range(_DEFAULT_LIMIT_PER_MINUTE + 10):
            resp = client.get("/api/v1/methodology/correlation-weights")
            last_status = resp.status_code
            if resp.status_code == 429:
                break
        else:
            pytest.fail(
                "Undecorated /methodology route never returned 429 within "
                f"{_DEFAULT_LIMIT_PER_MINUTE + 10} requests — the global "
                "default limit is not being enforced (SlowAPIMiddleware missing?)."
            )
        assert last_status == 429

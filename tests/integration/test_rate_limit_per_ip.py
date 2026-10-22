"""Public-endpoint rate limits bucket per IP (not per API key).

Two simulated IPs should get independent buckets — one IP hitting its cap
must not affect the other. Mirrors test_rate_limit_buckets_are_per_key on
the admin side.

Implementation note: the cold cases query is mocked so each request is
effectively instant. With 60+ requests needed to trigger the per-minute
limit, the rolling window would reset before the test could complete if
we hit a real DB. Mocking lets us actually exercise the rate-limit logic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from casesignal.api.app import create_app
from casesignal.api.dependencies.db import get_db_session

pytestmark = pytest.mark.integration


_PUBLIC_LIMIT_PER_MINUTE = 60  # matches @limiter.limit("60/minute") on /cold-cases/map


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Any:
    """Rate limit buckets live in a module-level singleton's in-memory storage,
    shared across every app created by create_app() in the same process.
    Reset before/after each test so bucket state can't leak in or out.

    The leading underscore on _storage is an slowapi internal, but it's the
    canonical escape hatch and stable across 0.1.x. The assert guards against
    slowapi API drift — if this fires, the reset strategy needs updating."""
    from casesignal.api.middleware.rate_limit import limiter

    assert hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"), (
        "slowapi internal API changed — limiter._storage.reset() no longer "
        "available. Find the new reset path before relying on this fixture."
    )
    limiter._storage.reset()
    yield
    limiter._storage.reset()


def test_separate_ips_get_independent_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch the IP extractor to read X-Forwarded-For for test purposes
    # (production trusts this via LB2, documented as a deploy blocker).
    # Patch target is the module-level binding in rate_limit.py, which
    # _key_func looks up via globals at call time. Patching slowapi.util
    # directly would not affect the already-imported reference.
    from casesignal.api.middleware import rate_limit as rl

    def _fake_remote_address(request: Request) -> str:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return "127.0.0.1"

    monkeypatch.setattr(rl, "get_remote_address", _fake_remote_address)

    app = create_app()

    def override_db() -> Any:
        # /cold-cases/map service issues a single PostGIS query and returns
        # a list of rows. Mock the session so every call yields an empty list.
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.__iter__ = lambda self: iter([])
        yield mock_session

    app.dependency_overrides[get_db_session] = override_db

    with TestClient(app) as client:

        def _hit(ip: str) -> Any:
            return client.get(
                "/api/v1/cold-cases/map",
                params={"bbox": "-78.5,36.5,-77.5,37.5"},
                headers={"X-Forwarded-For": ip},
            )

        # IP A burns through its bucket
        for _ in range(_PUBLIC_LIMIT_PER_MINUTE + 5):
            resp = _hit("203.0.113.1")
            if resp.status_code == 429:
                break
        else:
            pytest.fail("IP A should have hit 429 within the loop; rate limit is not firing.")

        # IP B is a distinct bucket; first request should not be 429.
        resp_b = _hit("203.0.113.2")
        assert resp_b.status_code != 429, (
            f"IP B got 429 on first request — bucketing leaked between IPs. "
            f"Response: {resp_b.text[:200]}"
        )

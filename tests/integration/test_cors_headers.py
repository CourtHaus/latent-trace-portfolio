"""CORS middleware attaches headers on allowed origins, not on disallowed
ones, and preserves them on error responses like 429."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from casesignal.api.app import create_app
from casesignal.api.dependencies.db import get_db_session

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Any:
    from casesignal.api.middleware.rate_limit import limiter

    assert hasattr(limiter, "_storage") and hasattr(
        limiter._storage, "reset"
    ), "slowapi internal API changed — see test_rate_limit_per_ip.py"
    limiter._storage.reset()
    yield
    limiter._storage.reset()


@pytest.fixture
def cors_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # TestClient's default Origin is http://testserver; configure CORS to allow it.
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://testserver,https://prod.example.com")
    app = create_app()

    def override_db() -> Any:
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.__iter__ = lambda self: iter([])
        yield mock_session

    app.dependency_overrides[get_db_session] = override_db
    with TestClient(app) as c:
        yield c


def test_cors_header_present_for_allowlisted_origin(cors_client: TestClient) -> None:
    resp = cors_client.get(
        "/api/v1/cold-cases/map",
        params={"bbox": "-78.5,36.5,-77.5,37.5"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://testserver"


def test_cors_header_absent_for_non_allowlisted_origin(cors_client: TestClient) -> None:
    resp = cors_client.get(
        "/api/v1/cold-cases/map",
        params={"bbox": "-78.5,36.5,-77.5,37.5"},
        headers={"Origin": "http://evil.example.com"},
    )
    # Starlette's CORSMiddleware omits allow-origin for unknown origins.
    # The request itself still succeeds (200) — CORS is a browser-enforcement
    # contract, not a server-side block.
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") is None


def test_cors_header_preserved_on_rate_limited_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 responses must carry CORS headers so the browser surfaces the real
    error instead of a generic CORS failure. Failing this test means
    CORSMiddleware is not the outermost layer.

    The DB is mocked so each request is effectively instant — with 60+
    requests needed, real DB latency would let the 60/min rolling window
    reset and the test would never observe a 429."""
    from casesignal.api.middleware import rate_limit as rl

    # Force every request into the same bucket by pinning the IP.
    # Patching rl.get_remote_address works because _key_func resolves it
    # via module globals at call time — unlike _key_func itself, which the
    # Limiter captured by reference at construction.
    monkeypatch.setattr(rl, "get_remote_address", lambda request: "10.0.0.1")
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://testserver,https://prod.example.com")

    app = create_app()

    def override_db() -> Any:
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.__iter__ = lambda self: iter([])
        yield mock_session

    app.dependency_overrides[get_db_session] = override_db

    with TestClient(app) as client:
        # /cold-cases/map carries @limiter.limit("60/minute").
        resp = None
        for _ in range(65):
            resp = client.get(
                "/api/v1/cold-cases/map",
                params={"bbox": "-78.5,36.5,-77.5,37.5"},
                headers={"Origin": "http://testserver"},
            )
            if resp.status_code == 429:
                break
        else:
            pytest.fail("Expected 429 within 65 iterations; rate limit is not firing.")

    assert resp.headers.get("access-control-allow-origin") == "http://testserver", (
        f"429 response missing access-control-allow-origin. CORSMiddleware "
        f"is likely not the outermost layer. Response headers: {dict(resp.headers)}"
    )

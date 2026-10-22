"""SEC-001 cluster: APP_ENV=dev bypass elimination.

Closes SEC-001, SEC-008, SEC-011, SEC-025, SEC-030.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_production_without_api_key_returns_401(production_client: TestClient) -> None:
    """SEC-001: Admin-gated routes must return 401 without X-Api-Key when APP_ENV=production.

    Narrowed post-A0: `/api/v1/analytics/*` is now public (no auth). The admin
    surface remains the authoritative test of the "no api key = 401" invariant.
    """
    resp = production_client.get("/api/v1/admin/keys")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Unauthorized."


def test_production_with_invalid_key_returns_401(production_client: TestClient) -> None:
    """SEC-001: Invalid keys must 401 on admin routes in production."""
    resp = production_client.get(
        "/api/v1/admin/keys",
        headers={"X-Api-Key": "not-a-real-key"},
    )
    assert resp.status_code == 401


def test_app_env_unset_raises_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-011: Missing APP_ENV must not silently fall back to 'dev'."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import importlib

    from casesignal.etl import config as config_module

    with pytest.raises((RuntimeError, ValueError)):
        importlib.reload(config_module)


def test_config_default_is_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-011: The APP_ENV default must be 'production', not 'dev'."""
    monkeypatch.delenv("APP_ENV", raising=False)
    # DATABASE_URL + KEY_HMAC_SECRET must be explicitly set in non-dev
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")
    monkeypatch.setenv("KEY_HMAC_SECRET", "test-secret-for-production-default-check")

    import importlib

    from casesignal.etl import config as config_module

    importlib.reload(config_module)
    assert config_module.settings.app_env == "production"


def test_production_without_frontend_origins_raises_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production startup must fail loudly if FRONTEND_ORIGINS is unset; the
    silent localhost:3000 fallback would block the real frontend in prod."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("FRONTEND_ORIGINS", raising=False)

    from casesignal.api.app import create_app

    with pytest.raises(RuntimeError, match="FRONTEND_ORIGINS"):
        create_app()

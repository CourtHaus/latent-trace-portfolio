"""Shared fixtures for security regression tests.

After Task 3 lands, settings.app_env is no longer read inside require_api_key —
tests rely on dependency_overrides, not env vars, for auth behavior. The
`production_client` name is kept to make intent obvious (it's the client that
enforces real auth), even though there is no runtime branch on APP_ENV anymore.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from casesignal.api.app import create_app
from casesignal.api.dependencies.auth import AuthenticatedKey, require_api_key


@pytest.fixture(autouse=True)
def _ensure_hmac_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Security tests assert HMAC behavior, which requires a non-empty secret.
    require_api_key reads KEY_HMAC_SECRET at call-time, so any value works as
    long as it's consistent between key issuance and validation within a test.
    """
    if not os.environ.get("KEY_HMAC_SECRET"):
        monkeypatch.setenv("KEY_HMAC_SECRET", "test-hmac-secret-for-security-tests")


@pytest.fixture
def production_client() -> Iterator[TestClient]:
    """TestClient with no auth override — exercises real require_api_key."""
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client() -> Iterator[TestClient]:
    """TestClient with require_api_key overridden to return a synthetic admin key."""
    app = create_app()

    def override_key(request: Request) -> AuthenticatedKey:
        request.state.api_key_id = 999
        return AuthenticatedKey(key_id=999, role="admin")

    app.dependency_overrides[require_api_key] = override_key
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session() -> Iterator[Session]:
    """SQLAlchemy Session bound to the same DATABASE_URL the TestClient uses.

    Used by tests that need to seed rows (e.g., issue a real API key row) and
    then exercise the TestClient against the same DB.
    """
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as s:
        yield s
    engine.dispose()


# Labels used by the key-issuing helpers in this directory's test modules
# (test_key_hmac_migration.py, test_key_lifecycle.py). Kept in sync with
# those helpers — any new fixture key label belongs here too.
_FIXTURE_KEY_LABELS = ("test-key", "hmac-test-key")


@pytest.fixture(autouse=True)
def _purge_fixture_api_keys() -> Iterator[None]:
    """Delete fixture-issued app_auth.api_keys rows after each security test.

    Several security tests INSERT real key rows directly to exercise the
    HMAC auth path. Without teardown those rows accumulate indefinitely —
    500+ were observed in a long-lived dev DB. Purge them by label after
    each test so the table stays clean. Runs on its own short-lived engine
    so it doesn't depend on a test having requested `db_session`.

    Best-effort: a few tests in this directory deliberately delete or point
    DATABASE_URL at a non-existent host (config-enforcement tests). Those
    issue no keys, so a failed connect here is harmless — swallow it rather
    than fail an otherwise-passing test on cleanup.
    """
    yield
    url = os.environ.get("DATABASE_URL")
    if not url:
        return
    try:
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM app_auth.api_keys WHERE label = ANY(:labels)"),
                    {"labels": list(_FIXTURE_KEY_LABELS)},
                )
        finally:
            engine.dispose()
    except SQLAlchemyError:
        # DATABASE_URL points nowhere (a config-enforcement test mangled it).
        # No keys were issued under that URL — nothing to purge.
        pass

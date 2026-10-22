"""
Integration tests for /api/v1/admin/keys against a real Postgres.

require_admin is overridden at the app level so we exercise the SQL
path directly, not the auth plumbing (that's covered by
tests/unit/test_route_auth.py).

All created keys are cleaned up via explicit DELETE at teardown so the
tests can run repeatedly on the same database.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from casesignal.api.app import create_app
from casesignal.api.dependencies.auth import AuthenticatedKey, require_admin
from casesignal.api.dependencies.db import get_db_session


@pytest.fixture(autouse=True)
def _set_hmac_secret(monkeypatch: MonkeyPatch) -> None:
    """KEY_HMAC_SECRET is read at call-time by the create endpoint + auth
    dependency. Tests in this module need it set to exercise the HMAC path;
    individual tests may override (e.g. delenv to test the misconfig branch).
    """
    monkeypatch.setenv("KEY_HMAC_SECRET", "x" * 64)


@pytest.fixture
def api_client(db_engine: Engine) -> Any:
    try:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres not reachable: {exc}")

    app = create_app()

    def _session_override() -> Any:
        Session = sessionmaker(bind=db_engine)
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[require_admin] = lambda: AuthenticatedKey(key_id=None, role="admin")
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def cleanup_keys(db_engine: Engine) -> Any:
    created_ids: list[int] = []
    yield created_ids
    if not created_ids:
        return
    with db_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM app_auth.api_keys WHERE key_id = ANY(:ids)"),
            {"ids": created_ids},
        )


def _create(client: Any, cleanup_keys: Any, *, label: Any, role: Any) -> Any:
    response = client.post("/api/v1/admin/keys", json={"label": label, "role": role})
    assert response.status_code == 201, response.text
    body = response.json()
    cleanup_keys.append(body["key_id"])
    return body


def test_list_returns_keys_after_create(api_client: Any, cleanup_keys: Any) -> None:
    created = _create(api_client, cleanup_keys, label="integration-list-test", role="reader")

    response = api_client.get("/api/v1/admin/keys")
    assert response.status_code == 200
    keys = response.json()

    match = next((k for k in keys if k["key_id"] == created["key_id"]), None)
    assert match is not None, f"Created key {created['key_id']} not found in list"
    assert match["label"] == "integration-list-test"
    assert match["role"] == "reader"
    assert match["revoked_at"] is None
    assert "key_hash" not in match


def test_list_excludes_revoked_by_default(api_client: Any, cleanup_keys: Any) -> None:
    created = _create(api_client, cleanup_keys, label="to-revoke", role="reader")

    revoke_response = api_client.delete(f"/api/v1/admin/keys/{created['key_id']}")
    assert revoke_response.status_code == 204

    default_list = api_client.get("/api/v1/admin/keys").json()
    assert not any(k["key_id"] == created["key_id"] for k in default_list)

    with_revoked = api_client.get("/api/v1/admin/keys?include_revoked=true").json()
    revoked = next((k for k in with_revoked if k["key_id"] == created["key_id"]), None)
    assert revoked is not None
    assert revoked["revoked_at"] is not None


def test_list_filters_by_role(api_client: Any, cleanup_keys: Any) -> None:
    reader = _create(api_client, cleanup_keys, label="r-filter", role="reader")
    operator = _create(api_client, cleanup_keys, label="o-filter", role="operator")

    readers = api_client.get("/api/v1/admin/keys?role=reader").json()
    reader_ids = {k["key_id"] for k in readers}
    assert reader["key_id"] in reader_ids
    assert operator["key_id"] not in reader_ids
    assert all(k["role"] == "reader" for k in readers)


def test_list_ordered_by_key_id(api_client: Any, cleanup_keys: Any) -> None:
    first = _create(api_client, cleanup_keys, label="order-1", role="reader")
    second = _create(api_client, cleanup_keys, label="order-2", role="reader")

    keys = api_client.get("/api/v1/admin/keys").json()
    positions = {k["key_id"]: index for index, k in enumerate(keys)}
    assert positions[first["key_id"]] < positions[second["key_id"]]


# --- Regression tests for the HMAC storage fix (PR #91) ---


def test_create_returns_plaintext_key_and_prefix(
    api_client: Any, cleanup_keys: Any, monkeypatch: MonkeyPatch
) -> None:
    """The plaintext key is returned exactly once on creation; callers depend
    on this since the server never stores it (only the HMAC digest).
    """
    monkeypatch.setenv("KEY_HMAC_SECRET", "x" * 64)
    created = _create(api_client, cleanup_keys, label="hmac-plaintext-test", role="reader")

    assert "key" in created, "response must include plaintext `key` field"
    assert "key_prefix" in created, "response must include `key_prefix` field"

    key: str = created["key"]
    prefix: str = created["key_prefix"]
    assert key.startswith("csk_"), f"key should be csk_-prefixed, got {key[:8]!r}..."
    assert len(key) == 64, f"key should be 64 chars, got {len(key)}"
    assert prefix == key[:12], "key_prefix should be first 12 chars of key"


def test_create_stores_hmac_and_prefix(
    api_client: Any, cleanup_keys: Any, db_engine: Engine, monkeypatch: MonkeyPatch
) -> None:
    """New keys must store key_hmac + key_prefix."""
    monkeypatch.setenv("KEY_HMAC_SECRET", "x" * 64)
    created = _create(api_client, cleanup_keys, label="hmac-storage-test", role="reader")

    with db_engine.connect() as connection:
        row = connection.execute(
            text("SELECT key_hmac, key_prefix" "  FROM app_auth.api_keys WHERE key_id = :k"),
            {"k": created["key_id"]},
        ).fetchone()

    assert row is not None
    assert row.key_hmac is not None, "key_hmac must be set on new keys"
    assert row.key_prefix is not None, "key_prefix must be set on new keys"
    assert row.key_prefix == created["key_prefix"]


def test_returned_key_authenticates_round_trip(
    api_client: Any, cleanup_keys: Any, db_engine: Engine, monkeypatch: MonkeyPatch
) -> Any:
    """The plaintext key returned on creation authenticates via the
    require_api_key dependency through the HMAC read path.

    Exercises the real auth path (no override) — proves the create → use
    round trip works end-to-end with the HMAC storage.
    """
    from fastapi import Depends
    from fastapi.testclient import TestClient

    from casesignal.api.app import create_app
    from casesignal.api.dependencies.auth import require_api_key

    monkeypatch.setenv("KEY_HMAC_SECRET", "x" * 64)
    created = _create(api_client, cleanup_keys, label="hmac-roundtrip-test", role="reader")
    plaintext = created["key"]

    # Build a small app that exercises require_api_key directly so we don't
    # depend on which other routes use it.
    probe_app = create_app()

    @probe_app.get("/_probe/auth")
    def _probe(auth: Any = Depends(require_api_key)) -> dict[str, Any]:
        return {"key_id": auth.key_id, "role": auth.role}

    def _session_override() -> Any:
        Session = sessionmaker(bind=db_engine)
        s = Session()
        try:
            yield s
        finally:
            s.close()

    probe_app.dependency_overrides[get_db_session] = _session_override
    probe_client = TestClient(probe_app)

    # No header → 401
    no_header = probe_client.get("/_probe/auth")
    assert no_header.status_code == 401

    # Valid plaintext → 200
    ok = probe_client.get("/_probe/auth", headers={"X-Api-Key": plaintext})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["role"] == "reader"
    assert body["key_id"] == created["key_id"]

    probe_app.dependency_overrides.clear()


def test_create_500s_when_hmac_secret_missing(api_client: Any, monkeypatch: MonkeyPatch) -> None:
    """Server-side configuration error → generic 500, no leak of the cause."""
    monkeypatch.delenv("KEY_HMAC_SECRET", raising=False)
    response = api_client.post(
        "/api/v1/admin/keys", json={"label": "missing-secret-test", "role": "reader"}
    )
    assert response.status_code == 500
    # Generic message; never echoes "KEY_HMAC_SECRET" or any internal detail.
    detail = response.json().get("detail", "")
    assert "KEY_HMAC_SECRET" not in detail
    assert "hmac" not in detail.lower()

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from casesignal.api.app import create_app
from casesignal.api.dependencies.auth import AuthenticatedKey, require_admin
from casesignal.api.dependencies.db import get_db_session


class _FakeRow:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self.__dict__.update(mapping)


class _FakeResult:
    def __init__(self, rows: Any) -> None:
        self._rows = rows

    def fetchall(self) -> Any:
        return self._rows


class _FakeKeysSession:
    """Records the SQL and params, returns the seeded rows regardless of filter."""

    def __init__(self, rows: Any) -> None:
        self._rows = rows
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: Any = None) -> Any:
        self.executed.append((str(statement), dict(params or {})))
        return _FakeResult(self._rows)


def _now() -> datetime:
    return datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)


def _row(key_id: Any = 1, label: Any = "k", role: Any = "reader", revoked: Any = False) -> Any:
    return _FakeRow(
        {
            "key_id": key_id,
            "label": label,
            "role": role,
            "created_at": _now(),
            "revoked_at": _now() if revoked else None,
            "expires_at": None,
            "last_used_at": None,
        }
    )


def _build_client(rows: Any) -> Any:
    session = _FakeKeysSession(rows)
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[require_admin] = lambda: AuthenticatedKey(key_id=1, role="admin")
    client = TestClient(app)
    return client, session, app


def test_list_returns_serialized_rows_and_excludes_key_hash() -> None:
    client, session, app = _build_client([_row(key_id=1, label="prod", role="admin")])
    try:
        response = client.get("/api/v1/admin/keys")
        assert response.status_code == 200
        body = response.json()
        assert body == [
            {
                "key_id": 1,
                "label": "prod",
                "role": "admin",
                "created_at": "2026-04-19T12:00:00Z",
                "revoked_at": None,
                "expires_at": None,
                "last_used_at": None,
            }
        ]
        sql = session.executed[0][0]
        assert "key_hash" not in sql, "key_hash must never be selected by the list endpoint"
    finally:
        app.dependency_overrides.clear()


def test_list_default_excludes_revoked() -> None:
    client, session, app = _build_client([])
    try:
        client.get("/api/v1/admin/keys")
        sql, params = session.executed[0]
        assert "revoked_at IS NULL" in sql
        assert "role" not in params
    finally:
        app.dependency_overrides.clear()


def test_list_include_revoked_drops_active_filter() -> None:
    client, session, app = _build_client([])
    try:
        client.get("/api/v1/admin/keys?include_revoked=true")
        sql, _ = session.executed[0]
        assert "revoked_at IS NULL" not in sql
    finally:
        app.dependency_overrides.clear()


def test_list_role_filter_binds_parameter() -> None:
    client, session, app = _build_client([])
    try:
        client.get("/api/v1/admin/keys?role=operator")
        sql, params = session.executed[0]
        assert "role = :role" in sql
        assert params["role"] == "operator"
    finally:
        app.dependency_overrides.clear()


def test_list_rejects_invalid_role_value() -> None:
    client, _, app = _build_client([])
    try:
        response = client.get("/api/v1/admin/keys?role=superuser")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_list_returns_empty_list_when_no_keys() -> None:
    client, _, app = _build_client([])
    try:
        response = client.get("/api/v1/admin/keys")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_orders_by_key_id() -> None:
    client, session, app = _build_client([])
    try:
        client.get("/api/v1/admin/keys")
        sql, _ = session.executed[0]
        assert "ORDER BY key_id" in sql
    finally:
        app.dependency_overrides.clear()

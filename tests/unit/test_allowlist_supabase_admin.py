from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.sql.base import Executable

from scripts.allowlist_supabase_admin import AdminUserRow, AuthUserRow, allowlist_admin_user


@dataclass
class FakeRow:
    id: str
    email: str


@dataclass
class FakeAdminRow:
    supabase_user_id: str


class FakeResult:
    def __init__(
        self,
        row: FakeRow | None = None,
        *,
        rows: list[FakeAdminRow] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []

    def one_or_none(self) -> AuthUserRow | None:
        return self._row

    def all(self) -> Sequence[AdminUserRow]:
        return self._rows


class FakeSession:
    def __init__(
        self,
        auth_row: FakeRow | None,
        *,
        admin_rows: list[FakeAdminRow] | None = None,
    ) -> None:
        self.auth_row = auth_row
        self.admin_rows = admin_rows or []
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.committed = False

    def execute(
        self,
        statement: Executable,
        params: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    ) -> FakeResult:
        sql = str(statement)
        if params is None:
            statement_params: dict[str, Any] = {}
        elif isinstance(params, Mapping):
            statement_params = dict(params)
        else:
            raise AssertionError("FakeSession only supports mapping execute params")
        self.statements.append((sql, statement_params))
        if "FROM auth.users" in sql:
            return FakeResult(self.auth_row)
        if "FROM app_auth.admin_user" in sql:
            return FakeResult(rows=self.admin_rows)
        return FakeResult()

    def commit(self) -> None:
        self.committed = True


def test_allowlist_admin_user_inserts_enabled_admin() -> None:
    session = FakeSession(FakeRow(id="11111111-1111-1111-1111-111111111111", email="Admin@Example.com"))
    result = allowlist_admin_user(session, email="admin@example.com")
    assert result == "11111111-1111-1111-1111-111111111111"
    assert session.committed is True
    admin_select_sql = session.statements[1][0]
    admin_select_params = session.statements[1][1]
    insert_sql = session.statements[2][0]
    insert_params = session.statements[2][1]
    assert "FROM app_auth.admin_user" in admin_select_sql
    assert "supabase_user_id = CAST(:user_id AS uuid)" in admin_select_sql
    assert "LOWER(email) = :normalized_email" in admin_select_sql
    assert "FOR UPDATE" in admin_select_sql
    assert admin_select_params["normalized_email"] == "admin@example.com"
    assert "INSERT INTO app_auth.admin_user" in insert_sql
    assert insert_params["email"] == "Admin@Example.com"
    assert insert_params["enabled"] is True


def test_allowlist_admin_user_updates_existing_admin_as_disabled() -> None:
    session = FakeSession(
        FakeRow(id="22222222-2222-2222-2222-222222222222", email="admin@example.com"),
        admin_rows=[FakeAdminRow(supabase_user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
    )
    result = allowlist_admin_user(session, email="ADMIN@example.com", enabled=False)
    assert result == "22222222-2222-2222-2222-222222222222"
    assert session.committed is True
    select_params = session.statements[0][1]
    admin_select_sql = session.statements[1][0]
    update_sql = session.statements[2][0]
    update_params = session.statements[2][1]
    assert len(session.statements) == 3
    assert select_params["email"] == "admin@example.com"
    assert "FROM app_auth.admin_user" in admin_select_sql
    assert "supabase_user_id = CAST(:user_id AS uuid)" in admin_select_sql
    assert "LOWER(email) = :normalized_email" in admin_select_sql
    assert "FOR UPDATE" in admin_select_sql
    assert "UPDATE app_auth.admin_user" in update_sql
    assert "WHERE supabase_user_id = CAST(:existing_user_id AS uuid)" in update_sql
    assert update_params["existing_user_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert update_params["user_id"] == "22222222-2222-2222-2222-222222222222"
    assert update_params["email"] == "admin@example.com"
    assert update_params["normalized_email"] == "admin@example.com"
    assert update_params["enabled"] is False


def test_allowlist_admin_user_raises_on_conflicting_admin_rows() -> None:
    session = FakeSession(
        FakeRow(id="33333333-3333-3333-3333-333333333333", email="admin@example.com"),
        admin_rows=[
            FakeAdminRow(supabase_user_id="33333333-3333-3333-3333-333333333333"),
            FakeAdminRow(supabase_user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        ],
    )
    with pytest.raises(RuntimeError, match="Conflicting admin allowlist rows"):
        allowlist_admin_user(session, email="admin@example.com", enabled=False)
    assert session.committed is False
    assert len(session.statements) == 2
    assert "FROM app_auth.admin_user" in session.statements[1][0]


def test_allowlist_admin_user_raises_when_auth_user_missing() -> None:
    session = FakeSession(None)
    with pytest.raises(RuntimeError, match="No Supabase Auth user found"):
        allowlist_admin_user(session, email="missing@example.com")


def test_allowlist_admin_user_rejects_blank_email_before_querying() -> None:
    session = FakeSession(None)
    with pytest.raises(RuntimeError, match="Email must not be blank"):
        allowlist_admin_user(session, email="   ")
    assert session.statements == []
    assert session.committed is False

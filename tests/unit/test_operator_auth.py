from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from casesignal.api.dependencies.operator_auth import (
    SupabaseAdminUser,
    _extract_bearer_token,
    require_operator_admin,
    verify_supabase_access_token,
)


class FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def one_or_none(self) -> Any:
        return self._row


class FakeSession:
    def __init__(self, row: Any) -> None:
        self.row = row
        self.params: dict[str, Any] | None = None

    def execute(self, statement: Any, params: dict[str, Any]) -> FakeResult:
        self.params = params
        return FakeResult(self.row)


def _response(status_code: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", "https://example.test"))


def test_extract_bearer_token_requires_authorization_header() -> None:
    with pytest.raises(HTTPException) as exc:
        _extract_bearer_token(None)
    assert exc.value.status_code == 401


def test_extract_bearer_token_rejects_non_bearer_header() -> None:
    with pytest.raises(HTTPException) as exc:
        _extract_bearer_token("Basic abc")
    assert exc.value.status_code == 401


def test_extract_bearer_token_returns_token() -> None:
    assert _extract_bearer_token("Bearer abc.def") == "abc.def"


def test_verify_supabase_access_token_calls_auth_user_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", " https://project.supabase.co/ ")
    monkeypatch.setenv("SUPABASE_ANON_KEY", " anon ")

    captured: dict[str, Any] = {}

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _response(
            200,
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "email": "admin@example.com",
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    user = verify_supabase_access_token("token")
    assert user.supabase_user_id == "11111111-1111-1111-1111-111111111111"
    assert user.email == "admin@example.com"
    assert captured["url"] == "https://project.supabase.co/auth/v1/user"
    assert captured["headers"]["apikey"] == "anon"
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["timeout"] == 5.0


def test_verify_supabase_access_token_uses_stripped_fallback_anon_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", " fallback-anon ")

    captured: dict[str, Any] = {}

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        captured["headers"] = headers
        return _response(
            200,
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "email": "admin@example.com",
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    verify_supabase_access_token("token")
    assert captured["headers"]["apikey"] == "fallback-anon"


def test_verify_supabase_access_token_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _response(401, {"message": "bad"}))
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("bad")
    assert exc.value.status_code == 401


def test_verify_supabase_access_token_rejects_forbidden_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _response(403, {"message": "bad"}))
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("bad")
    assert exc.value.status_code == 401


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_verify_supabase_access_token_raises_service_error_for_supabase_outage(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _response(status_code, {"message": "unavailable"}))
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("token")
    assert exc.value.status_code == 503
    assert exc.value.detail == "Supabase auth is temporarily unavailable."


def test_verify_supabase_access_token_raises_service_error_for_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")

    def fake_get(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("token")
    assert exc.value.status_code == 503
    assert exc.value.detail == "Supabase auth is temporarily unavailable."


def test_verify_supabase_access_token_rejects_invalid_uuid_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _response(200, {"id": "not-a-uuid"}))
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("token")
    assert exc.value.status_code == 401


def test_verify_supabase_access_token_rejects_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            content=b"not json",
            request=httpx.Request("GET", "https://example.test"),
        ),
    )
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("token")
    assert exc.value.status_code == 401


def test_verify_supabase_access_token_rejects_non_object_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            json=["not", "an", "object"],
            request=httpx.Request("GET", "https://example.test"),
        ),
    )
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("token")
    assert exc.value.status_code == 401


def test_verify_supabase_access_token_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("token")
    assert exc.value.status_code == 500


def test_verify_supabase_access_token_requires_anon_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", " ")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", " ")
    with pytest.raises(HTTPException) as exc:
        verify_supabase_access_token("token")
    assert exc.value.status_code == 500


def test_require_operator_admin_rejects_non_allowlisted_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "casesignal.api.dependencies.operator_auth.verify_supabase_access_token",
        lambda token: SupabaseAdminUser(
            supabase_user_id="11111111-1111-1111-1111-111111111111",
            email="not-admin@example.com",
        ),
    )
    with pytest.raises(HTTPException) as exc:
        require_operator_admin(
            authorization="Bearer token",
            session=FakeSession(row=None),  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 403


def test_require_operator_admin_returns_allowlisted_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "casesignal.api.dependencies.operator_auth.verify_supabase_access_token",
        lambda token: SupabaseAdminUser(
            supabase_user_id="11111111-1111-1111-1111-111111111111",
            email="admin@example.com",
        ),
    )
    row = MagicMock()
    row.supabase_user_id = "11111111-1111-1111-1111-111111111111"
    row.email = "admin@example.com"
    session = FakeSession(row=row)
    result = require_operator_admin(
        authorization="Bearer token",
        session=session,  # type: ignore[arg-type]
    )
    assert result.supabase_user_id == "11111111-1111-1111-1111-111111111111"
    assert result.email == "admin@example.com"
    assert session.params == {"supabase_user_id": "11111111-1111-1111-1111-111111111111"}

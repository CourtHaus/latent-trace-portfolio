from __future__ import annotations

import os
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.dependencies.db import get_db_session

# SEC-B04: this is a SEPARATE admin trust root from the API-key admin tier in
# dependencies/auth.py (require_admin). That one authenticates an
# app_auth.api_keys row with role='admin' (HMAC); this one authenticates a
# Supabase access token whose user is enabled in app_auth.admin_user. The two
# have independent credential stores and revocation paths — OFFBOARDING MUST
# revoke both: disable/remove the app_auth.admin_user row AND revoke any
# admin-role API keys. Kept deliberately separate (operator dashboard uses
# Supabase Auth; programmatic admin uses API keys).
SUPABASE_AUTH_UNAVAILABLE_DETAIL = "Supabase auth is temporarily unavailable."


@dataclass(frozen=True)
class SupabaseAdminUser:
    supabase_user_id: str
    email: str | None


def _extract_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Unauthorized.")
    return token.strip()


def _supabase_auth_user_url() -> str:
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if not supabase_url:
        raise HTTPException(status_code=500, detail="Supabase auth is not configured.")
    return f"{supabase_url}/auth/v1/user"


def _supabase_anon_key() -> str:
    anon_key = (os.environ.get("SUPABASE_ANON_KEY") or "").strip() or (
        os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or ""
    ).strip()
    if not anon_key:
        raise HTTPException(status_code=500, detail="Supabase auth is not configured.")
    return anon_key


def _raise_supabase_auth_unavailable() -> None:
    raise HTTPException(status_code=503, detail=SUPABASE_AUTH_UNAVAILABLE_DETAIL)


def verify_supabase_access_token(access_token: str) -> SupabaseAdminUser:
    try:
        response = httpx.get(
            _supabase_auth_user_url(),
            headers={
                "apikey": _supabase_anon_key(),
                "Authorization": f"Bearer {access_token}",
            },
            timeout=5.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=SUPABASE_AUTH_UNAVAILABLE_DETAIL) from exc

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Unauthorized.")
    if response.status_code == 429 or response.status_code >= 500:
        _raise_supabase_auth_unavailable()
    if response.status_code != 200:
        _raise_supabase_auth_unavailable()

    try:
        payload: Any = response.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Unauthorized.")
    user_id = payload.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    try:
        UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized.") from exc
    email = payload.get("email")
    return SupabaseAdminUser(
        supabase_user_id=user_id,
        email=email if isinstance(email, str) else None,
    )


def require_operator_admin(
    authorization: str | None = Header(None),
    session: Session = Depends(get_db_session),
) -> SupabaseAdminUser:
    token = _extract_bearer_token(authorization)
    user = verify_supabase_access_token(token)
    row = (
        session.execute(
            text(
                "SELECT supabase_user_id::text AS supabase_user_id, email"
                " FROM app_auth.admin_user"
                " WHERE supabase_user_id = CAST(:supabase_user_id AS uuid)"
                "   AND enabled IS TRUE"
            ),
            {"supabase_user_id": user.supabase_user_id},
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return SupabaseAdminUser(
        supabase_user_id=str(row.supabase_user_id),
        email=str(row.email) if row.email is not None else user.email,
    )

from __future__ import annotations

import hashlib
import hmac as _hmac
import os
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.dependencies.auth import AuthenticatedKey, require_admin
from casesignal.api.dependencies.db import get_db_session

router = APIRouter(prefix="/admin/keys", tags=["admin"])


# Only `admin` is enforced today (via require_admin). `reader`/`operator` are
# RESERVED for the planned public API tier (see require_operator in
# dependencies/auth.py, SEC-B03) and currently grant access to no endpoints —
# minting such a key is intentionally a no-op until that tier ships.
ApiKeyRole = Literal["reader", "operator", "admin"]


class CreateApiKeyRequest(BaseModel):
    label: str = Field(..., max_length=255)
    role: ApiKeyRole
    expires_at: datetime | None = None  # Nullable = never expires


class ApiKeyResponse(BaseModel):
    key_id: int
    label: str
    role: str
    created_at: datetime
    expires_at: datetime | None
    # The plaintext key is returned ONCE on creation. The server only stores
    # the HMAC; the plaintext cannot be recovered later. Callers must capture
    # it from this response. `key_prefix` is safe to log for correlation.
    key: str
    key_prefix: str


class ApiKeyListItem(BaseModel):
    key_id: int
    label: str
    role: str
    created_at: datetime
    revoked_at: datetime | None
    expires_at: datetime | None
    last_used_at: datetime | None


@router.post("", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    request: CreateApiKeyRequest,
    session: Session = Depends(get_db_session),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> ApiKeyResponse:
    # Read KEY_HMAC_SECRET at call time — matches the auth dependency's
    # call-time read so secret rotation (process restart) is reflected
    # without re-import.
    hmac_secret_str = os.environ.get("KEY_HMAC_SECRET", "")
    if not hmac_secret_str:
        # Server-side misconfiguration; do not leak that detail to the caller.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred.",
        )

    # Key format: "csk_" + 8 random hex + 52 random hex = 64-char key.
    # The first 12 chars ("csk_" + 8 hex) are stored as key_prefix for log
    # correlation; the full plaintext is hashed via HMAC-SHA256 and stored
    # in key_hmac.
    prefix_random = secrets.token_hex(4)
    secret_random = secrets.token_hex(26)
    plaintext_key = f"csk_{prefix_random}{secret_random}"
    key_prefix = plaintext_key[:12]
    hmac_secret = hmac_secret_str.encode()
    key_hmac = _hmac.new(hmac_secret, plaintext_key.encode(), hashlib.sha256).hexdigest()

    row = session.execute(
        text(
            "INSERT INTO app_auth.api_keys"
            " (key_hmac, key_prefix, label, role, expires_at)"
            " VALUES (:hmac, :prefix, :label, :role, :expires_at)"
            " RETURNING key_id, label, role, created_at, expires_at"
        ),
        {
            "hmac": key_hmac,
            "prefix": key_prefix,
            "label": request.label,
            "role": request.role,
            "expires_at": request.expires_at,
        },
    ).fetchone()
    session.commit()

    if row is None:
        # INSERT ... RETURNING produced no row — should be impossible given the
        # statement above. Raise loudly so the failure surfaces under `python -O`
        # where `assert` is stripped.
        raise RuntimeError("INSERT ... RETURNING produced no row from app_auth.api_keys")
    return ApiKeyResponse(
        key_id=row.key_id,
        label=row.label,
        role=row.role,
        created_at=row.created_at,
        expires_at=row.expires_at,
        key=plaintext_key,
        key_prefix=key_prefix,
    )


@router.get("", response_model=list[ApiKeyListItem])
def list_api_keys(
    include_revoked: bool = Query(default=False),
    role: ApiKeyRole | None = Query(default=None),
    session: Session = Depends(get_db_session),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> list[ApiKeyListItem]:
    clauses: list[str] = []
    params: dict[str, object] = {}

    if not include_revoked:
        clauses.append("revoked_at IS NULL")
    if role is not None:
        clauses.append("role = :role")
        params["role"] = role

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = session.execute(
        text(
            "SELECT key_id, label, role, created_at, revoked_at, expires_at, last_used_at"
            " FROM app_auth.api_keys"
            f"{where_sql}"
            " ORDER BY key_id"
        ),
        params,
    ).fetchall()

    return [
        ApiKeyListItem(
            key_id=row.key_id,
            label=row.label,
            role=row.role,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
            expires_at=row.expires_at,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: int,
    session: Session = Depends(get_db_session),
    _auth: AuthenticatedKey = Depends(require_admin),
) -> None:
    result = session.execute(
        text(
            "UPDATE app_auth.api_keys SET revoked_at = NOW()"
            " WHERE key_id = :key_id AND revoked_at IS NULL"
            " RETURNING key_id"
        ),
        {"key_id": key_id},
    ).fetchone()
    session.commit()

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

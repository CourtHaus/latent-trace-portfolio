from __future__ import annotations

import hashlib
import hmac as _hmac
import os
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.dependencies.db import get_db_session


@dataclass
class AuthenticatedKey:
    key_id: int | None
    role: str | None


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(None),
    session: Session = Depends(get_db_session),
) -> AuthenticatedKey:
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    # New-format HMAC lookup — read secret at call-time so env changes in tests
    # (and secret rotation via process restart) are reflected without reimport.
    hmac_secret = os.environ.get("KEY_HMAC_SECRET", "").encode()
    hmac_digest = _hmac.new(hmac_secret, x_api_key.encode(), hashlib.sha256).hexdigest()
    row = session.execute(
        text(
            "SELECT key_id, role FROM app_auth.api_keys"
            " WHERE key_hmac = :h AND revoked_at IS NULL"
            " AND (expires_at IS NULL OR expires_at > NOW())"
        ),
        {"h": hmac_digest},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    # Throttled usage tracking — write only when stale, so hot keys don't generate
    # a write on every request. Best-effort: never fail the request on write error.
    try:
        session.execute(
            text(
                "UPDATE app_auth.api_keys SET last_used_at = NOW()"
                " WHERE key_id = :k"
                " AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '1 minute')"
            ),
            {"k": row.key_id},
        )
        session.commit()
    except Exception:
        session.rollback()
    request.state.api_key_id = row.key_id
    return AuthenticatedKey(key_id=row.key_id, role=row.role)


def require_operator(
    auth_key: AuthenticatedKey = Depends(require_api_key),
) -> AuthenticatedKey:
    """RESERVED (SEC-B03): operator-tier API-key gate for the planned public API
    (read/analytics access for data scientists/journalists). Intentionally not
    wired to any route yet — there is no current consumer. Kept as a roadmap
    reservation rather than deleted; when the public API tier ships, attach this
    to those endpoints. Until then, minting a `reader`/`operator` key grants
    access to nothing (only `admin` is enforced, via require_admin).
    """
    if (auth_key.role or "").lower() not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="Operator privileges required.")
    return auth_key


def require_admin(
    auth_key: AuthenticatedKey = Depends(require_api_key),
) -> AuthenticatedKey:
    if (auth_key.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return auth_key

"""SEC-004: API key expiry + last_used_at tracking."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _issue_key(session: Any, *, role: str = "admin", expires_at: datetime | None = None) -> str:
    plaintext = "csk_" + secrets.token_hex(30)
    secret = os.environ["KEY_HMAC_SECRET"].encode()
    digest = hmac.new(secret, plaintext.encode(), hashlib.sha256).hexdigest()
    prefix = plaintext[:12]
    session.execute(
        text(
            "INSERT INTO app_auth.api_keys (key_hmac, key_prefix, label, role, expires_at) "
            "VALUES (:h, :p, :l, :r, :e)"
        ),
        {"h": digest, "p": prefix, "l": "test-key", "r": role, "e": expires_at},
    )
    session.commit()
    return plaintext


def _digest(plaintext: str) -> str:
    secret = os.environ["KEY_HMAC_SECRET"].encode()
    return hmac.new(secret, plaintext.encode(), hashlib.sha256).hexdigest()


def test_expired_key_is_rejected(production_client: Any, db_session: Session) -> None:
    """SEC-004: An expired key must 401 even when revoked_at is NULL."""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    key = _issue_key(db_session, expires_at=past)
    resp = production_client.get(
        "/api/v1/admin/keys",
        headers={"X-Api-Key": key},
    )
    assert resp.status_code == 401


def test_non_expired_key_succeeds(production_client: Any, db_session: Session) -> None:
    """SEC-004: A key with future expiry must still work."""
    future = datetime.now(timezone.utc) + timedelta(days=30)
    key = _issue_key(db_session, expires_at=future)
    resp = production_client.get(
        "/api/v1/admin/keys",
        headers={"X-Api-Key": key},
    )
    assert resp.status_code == 200


def test_null_expiry_means_no_expiry(production_client: Any, db_session: Session) -> None:
    """SEC-004: NULL expires_at must be treated as 'never expires'."""
    key = _issue_key(db_session, expires_at=None)
    resp = production_client.get(
        "/api/v1/admin/keys",
        headers={"X-Api-Key": key},
    )
    assert resp.status_code == 200


def test_last_used_at_updated_on_use(production_client: Any, db_session: Session) -> None:
    """SEC-004: last_used_at must be set to approximately now() on each validated request."""
    key = _issue_key(db_session, expires_at=None)
    digest = _digest(key)

    # Initially NULL
    row = (
        db_session.execute(
            text("SELECT last_used_at FROM app_auth.api_keys WHERE key_hmac = :h"),
            {"h": digest},
        )
        .mappings()
        .first()
    )
    assert row is not None
    assert row["last_used_at"] is None

    # Record time just before the request so we can bound last_used_at accurately
    # regardless of how long the endpoint takes to respond.
    before_request = datetime.now(timezone.utc)
    production_client.get(
        "/api/v1/admin/keys",
        headers={"X-Api-Key": key},
    )
    after_request = datetime.now(timezone.utc)

    # Expire the SQLAlchemy session identity map so we read the committed value.
    db_session.expire_all()
    row = (
        db_session.execute(
            text("SELECT last_used_at FROM app_auth.api_keys WHERE key_hmac = :h"),
            {"h": digest},
        )
        .mappings()
        .first()
    )
    assert row is not None
    assert row["last_used_at"] is not None
    # last_used_at must fall within the window of the request, with a 5-second buffer.
    assert row["last_used_at"] >= before_request - timedelta(seconds=5)
    assert row["last_used_at"] <= after_request + timedelta(seconds=5)

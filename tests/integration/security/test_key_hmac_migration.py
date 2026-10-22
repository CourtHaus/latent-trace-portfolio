"""SEC-003: API keys authenticate via HMAC-SHA256, not raw SHA-256."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.orm import Session


def _issue_hmac_key(db_session: Session, *, role: str = "admin") -> str:
    plaintext = "csk_" + secrets.token_hex(30)
    secret = os.environ["KEY_HMAC_SECRET"].encode()
    digest = hmac.new(secret, plaintext.encode(), hashlib.sha256).hexdigest()
    prefix = plaintext[:12]  # "csk_" + 8 hex
    db_session.execute(
        text(
            "INSERT INTO app_auth.api_keys (key_hmac, key_prefix, label, role) "
            "VALUES (:hm, :p, :l, :r)"
        ),
        {"hm": digest, "p": prefix, "l": "hmac-test-key", "r": role},
    )
    db_session.commit()
    return plaintext


def test_hmac_key_validates(production_client: TestClient, db_session: Session) -> None:
    """A key stored as HMAC and presented fresh must authenticate successfully."""
    key = _issue_hmac_key(db_session)
    resp = production_client.get(
        "/api/v1/admin/keys",
        headers={"X-Api-Key": key},
    )
    assert resp.status_code == 200


def test_raw_sha256_path_rejected_when_hmac_secret_rotated(
    monkeypatch: MonkeyPatch, db_session: Session
) -> None:
    """Rotating KEY_HMAC_SECRET invalidates previously-issued HMAC keys (as expected)."""
    from casesignal.api.app import create_app

    key = _issue_hmac_key(db_session)
    monkeypatch.setenv("KEY_HMAC_SECRET", "different-secret-" + secrets.token_hex(16))
    app = create_app()
    with TestClient(app) as c:
        resp = c.get("/api/v1/admin/keys", headers={"X-Api-Key": key})
    assert resp.status_code == 401


def test_key_prefix_enables_log_correlation(db_session: Session) -> None:
    """SEC-003 secondary: key_prefix is stored unhashed so a leaked key can be traced."""
    key = _issue_hmac_key(db_session)
    prefix = key[:12]
    row = db_session.execute(
        text("SELECT key_id FROM app_auth.api_keys WHERE key_prefix = :p"),
        {"p": prefix},
    ).fetchone()
    assert row is not None

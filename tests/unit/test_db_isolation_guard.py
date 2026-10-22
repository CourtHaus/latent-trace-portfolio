from __future__ import annotations

import os

import pytest

from tests.support import db_guard


def test_default_url_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert db_guard.resolve_test_database_url() == db_guard.DEFAULT_TEST_DATABASE_URL


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg2://u:p@h:5/other_test")
    assert db_guard.resolve_test_database_url() == "postgresql+psycopg2://u:p@h:5/other_test"


def test_marker_detection_against_live_test_db() -> None:
    # The active test DB (resolved + redirected by conftest) MUST carry the sentinel.
    assert db_guard.has_sentinel(os.environ["DATABASE_URL"]) is True


def test_marker_absent_for_nonexistent_table() -> None:
    # Detection logic: a name that does not exist returns False.
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as conn:
            assert db_guard._marker_exists(conn, "public._no_such_marker_xyz") is False
    finally:
        engine.dispose()


def test_enforce_raises_when_sentinel_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_guard, "has_sentinel", lambda _url: False)
    with pytest.raises(RuntimeError, match="not a CaseSignal test database"):
        db_guard.enforce_test_database("postgresql+psycopg2://u:p@h:5/live")


def test_enforce_converts_connection_error_to_friendly_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError

    def _boom(_url: str) -> bool:
        raise OperationalError("connect failed", None, Exception("refused"))

    monkeypatch.setattr(db_guard, "has_sentinel", _boom)
    with pytest.raises(RuntimeError, match="cannot connect to test database"):
        db_guard.enforce_test_database("postgresql+psycopg2://u:p@h:5/missing")

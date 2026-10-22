"""Verify migration 0013 leaves the DB with ``app_auth``, not the legacy ``auth``.

Background in ``migrations/versions/0013_rename_auth_schema_to_app_auth.py``.
"""
from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


@pytest.fixture
def engine() -> Any:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    return create_engine(db_url)


def test_app_auth_schema_exists(engine: Any) -> None:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = 'app_auth'"
            )
        ).scalar_one_or_none()
    assert result == "app_auth"


def test_legacy_auth_schema_renamed_away(engine: Any) -> None:
    """The legacy ``auth`` schema must not coexist with ``app_auth``.

    Supabase reserves ``auth`` for its own auth tables. If a project DB still
    has a non-Supabase ``auth`` schema after migration 0013, either the rename
    didn't run or something recreated the legacy schema afterwards.
    """
    with engine.connect() as conn:
        has_auth = conn.execute(
            text(
                "SELECT 1 FROM information_schema.schemata "
                "WHERE schema_name = 'auth' "
                # Supabase's own auth schema has well-known internal tables;
                # if we see those, the schema is Supabase's, not ours.
                "AND NOT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'auth' AND table_name = 'users'"
                ")"
            )
        ).scalar_one_or_none()
    assert has_auth is None, (
        "A non-Supabase ``auth`` schema still exists; migration 0013 should "
        "have renamed it to ``app_auth``."
    )


def test_app_auth_api_keys_table_present(engine: Any) -> None:
    """``app_auth.api_keys`` is the canonical auth table after the rename."""
    with engine.connect() as conn:
        table_name = conn.execute(
            text("SELECT to_regclass('app_auth.api_keys')")
        ).scalar_one()
    assert table_name == "app_auth.api_keys"

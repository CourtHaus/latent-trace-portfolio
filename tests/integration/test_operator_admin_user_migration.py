from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


def test_operator_admin_user_table_exists() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as conn:
            table_exists = conn.execute(
                text(
                    "SELECT EXISTS ("
                    " SELECT 1 FROM information_schema.tables"
                    " WHERE table_schema='app_auth' AND table_name='admin_user'"
                    ")"
                )
            ).scalar_one()
            columns = {
                row.column_name
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema='app_auth' AND table_name='admin_user'"
                    )
                )
            }
            email_index_definition = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes"
                    " WHERE schemaname='app_auth'"
                    " AND tablename='admin_user'"
                    " AND indexname='uq_admin_user_email_lower'"
                )
            ).scalar_one_or_none()
        assert table_exists is True
        assert columns == {
            "supabase_user_id",
            "email",
            "enabled",
            "created_at",
            "updated_at",
        }
        assert email_index_definition is not None
        assert "CREATE UNIQUE INDEX" in email_index_definition
        assert "lower(email)" in email_index_definition.lower()
    finally:
        engine.dispose()

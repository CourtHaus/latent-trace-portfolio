"""One-off cleanup for dev DBs in the auth/app_auth dual-schema state.

PR #113 changed the auth schema from ``auth`` → ``app_auth`` by editing
``migrations/versions/0001_baseline.py`` in place. Any dev DB that ran the
**original** 0001 still has the legacy ``auth.api_keys`` table. If the
edited 0001 was later re-run (e.g. someone re-created the schema, or
the DB was rebuilt with a checkout that included PR #113), the DB ended
up with **both** schemas present plus an FK from ``audit.ai_briefing``
still pointing at the legacy ``auth.api_keys``.

Migration 0013 refuses to proceed in this state. This script repairs it:

1. Verifies the legacy ``auth.api_keys`` is empty (refuses otherwise)
2. Drops any FKs that still point at the legacy table
3. Re-adds those FKs against ``app_auth.api_keys``
4. Drops ``auth.api_keys`` and the empty ``auth`` schema

After this script succeeds, ``alembic upgrade head`` will pick up
migration 0013 as a no-op (only ``app_auth`` will exist).

Usage:
    DATABASE_URL=... python scripts/cleanup_orphaned_auth_schema.py [--apply]

Without ``--apply``, the script reports what it would do and exits.
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the cleanup. Without this flag, runs in report-only mode.",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 1

    engine = create_engine(db_url)
    with engine.connect() as conn:
        has_auth = conn.execute(
            text(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth'"
            )
        ).scalar_one_or_none()
        has_app_auth = conn.execute(
            text(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app_auth'"
            )
        ).scalar_one_or_none()

        if not has_auth:
            print("OK: no legacy ``auth`` schema present; nothing to clean up.")
            return 0
        if not has_app_auth:
            print(
                "error: legacy ``auth`` schema exists but ``app_auth`` does not. "
                "Run `alembic upgrade head` instead — migration 0013 will rename for you.",
                file=sys.stderr,
            )
            return 1

        legacy_rows = conn.execute(
            text("SELECT COUNT(*) FROM auth.api_keys")
        ).scalar_one()
        if legacy_rows > 0:
            print(
                f"error: ``auth.api_keys`` has {legacy_rows} rows. Manual reconciliation "
                "required: decide whether to backfill ``app_auth.api_keys`` from these rows "
                "or treat them as stale duplicates.",
                file=sys.stderr,
            )
            return 1

        fks = conn.execute(
            text(
                """
                SELECT
                    n.nspname || '.' || c.relname AS source_table,
                    con.conname,
                    pg_get_constraintdef(con.oid) AS constraint_def
                FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_class tc ON tc.oid = con.confrelid
                JOIN pg_namespace tn ON tn.oid = tc.relnamespace
                WHERE tn.nspname = 'auth' AND tc.relname = 'api_keys'
                """
            )
        ).all()

        print("Plan:")
        for row in fks:
            print(f"  - drop FK {row.conname} on {row.source_table}")
            print("    re-add against app_auth.api_keys with same definition")
        print("  - drop table auth.api_keys")
        print("  - drop schema auth")

        if not args.apply:
            print("\n(report-only; re-run with --apply to execute)")
            return 0

    # --apply path: open a transaction and perform the edits.
    with engine.begin() as conn:
        for row in fks:
            new_def = row.constraint_def.replace("auth.api_keys", "app_auth.api_keys")
            conn.execute(
                text(f"ALTER TABLE {row.source_table} DROP CONSTRAINT {row.conname}")
            )
            conn.execute(
                text(
                    f"ALTER TABLE {row.source_table} "
                    f"ADD CONSTRAINT {row.conname} {new_def}"
                )
            )
        conn.execute(text("DROP TABLE auth.api_keys"))
        conn.execute(text("DROP SCHEMA auth"))

    print("OK: cleanup complete. Run `alembic upgrade head` to confirm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

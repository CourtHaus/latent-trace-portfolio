"""Rename legacy ``auth`` schema to ``app_auth`` for Supabase compat.

Revision ID: 0013
Revises: 0012

Background
----------
PR #113 changed the auth schema name from ``auth`` to ``app_auth`` to avoid
clashing with Supabase's built-in ``auth`` schema. The change was applied
by editing ``0001_baseline.py`` (and ``0009``) in place, which means:

- Any DB that ran the *post-edit* 0001 (e.g. live Supabase, fresh local
  setups after PR #113) already has ``app_auth.api_keys`` and no ``auth``
  schema → this migration is a no-op.
- Any DB that ran the *original* 0001 (every local dev DB created before
  PR #113) still has ``auth.api_keys`` even though all application code now
  queries ``app_auth.api_keys`` → silent runtime breakage. This migration
  renames the schema so the code matches reality.

The ``IF EXISTS`` guard makes the rename idempotent and safe to apply to
either DB shape. The downgrade is the symmetric reverse.
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The check anchors on whether OUR legacy table ``auth.api_keys`` exists,
    # not on whether a schema literally named ``auth`` exists. On Supabase the
    # ``auth`` schema always exists (it holds Supabase Auth's own tables —
    # auth.users, auth.refresh_tokens, auth.mfa_factors, etc.) and the original
    # "does schema ``auth`` exist" check would spuriously trip the corruption
    # branch on every Supabase project.
    #
    # Possible starting states:
    #   1. ``auth.api_keys`` exists, no ``app_auth`` → legacy local; rename schema
    #   2. ``auth.api_keys`` exists, ``app_auth`` also exists → corrupted dev DB
    #      from PR #113's in-place edit of 0001 → raise
    #   3. No ``auth.api_keys`` → either fresh deploy, Supabase (where ``auth`` is
    #      theirs), or rename has already happened → no-op
    op.execute(
        """
        DO $$
        DECLARE
            legacy_api_keys_in_auth BOOLEAN;
            has_app_auth            BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                 WHERE table_schema = 'auth' AND table_name = 'api_keys'
            ) INTO legacy_api_keys_in_auth;

            SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app_auth')
              INTO has_app_auth;

            IF legacy_api_keys_in_auth AND NOT has_app_auth THEN
                ALTER SCHEMA auth RENAME TO app_auth;
            ELSIF legacy_api_keys_in_auth AND has_app_auth THEN
                RAISE EXCEPTION
                    'Both legacy ``auth.api_keys`` and ``app_auth`` schemas exist. '
                    'This is a corrupted state from PR #113''s in-place 0001 edit. '
                    'Run ``tools/cleanup_orphaned_auth_schema.py`` to repoint any '
                    'FKs and drop the legacy schema, then re-run this migration.';
            END IF;
            -- All other paths are no-ops: fresh deploy, Supabase (auth schema
            -- belongs to Supabase Auth, no api_keys table in it), or rename
            -- already applied (auth.api_keys long gone, app_auth.api_keys is
            -- the new home).
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app_auth')
               AND NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth')
            THEN
                ALTER SCHEMA app_auth RENAME TO auth;
            END IF;
        END
        $$;
        """
    )

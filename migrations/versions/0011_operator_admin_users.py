"""Add app_auth.admin_user for Supabase-backed operator access.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_user",
        sa.Column("supabase_user_id", sa.UUID(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        schema="app_auth",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_admin_user_email_lower"
        " ON app_auth.admin_user (LOWER(email))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app_auth.uq_admin_user_email_lower")
    op.drop_table("admin_user", schema="app_auth")

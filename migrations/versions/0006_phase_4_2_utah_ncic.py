"""Phase 4.2 — Utah support: NCIC federal cross-reference column.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-11

Renumbered from 0005 → 0006 during rebase onto main because main now
includes 0005_add_landmark_geocode_precision (the Google-geocoding
landmark precision tier). The two migrations are independent — this
one adds a column, that one widens a CHECK constraint — so order is
arbitrary, but they need distinct revision numbers.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("ncic_case_id", sa.Text(), nullable=True),
        schema="cold_case",
    )


def downgrade() -> None:
    op.drop_column("cases", "ncic_case_id", schema="cold_case")

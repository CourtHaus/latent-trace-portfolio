"""Add cold_case.extraction_review for Tier-2 QA.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_VERDICTS = ("correct", "incorrect", "unsure")


def _verdict_check(column_name: str) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{verdict}'" for verdict in _VERDICTS)
    return sa.CheckConstraint(
        f"{column_name} IN ({allowed})",
        name=f"extraction_review_{column_name}_check",
    )


def upgrade() -> None:
    op.create_table(
        "extraction_review",
        sa.Column("review_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "case_id",
            sa.BigInteger(),
            sa.ForeignKey("cold_case.cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("prompt_tier", sa.SmallInteger(), nullable=False, server_default="2"),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("verdict_date", sa.Text()),
        sa.Column("verdict_address", sa.Text()),
        sa.Column("verdict_age", sa.Text()),
        sa.Column("verdict_gender", sa.Text()),
        sa.Column("verdict_race", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "case_id",
            "prompt_hash",
            "reviewer",
            name="extraction_review_case_id_prompt_hash_reviewer_key",
        ),
        _verdict_check("verdict_date"),
        _verdict_check("verdict_address"),
        _verdict_check("verdict_age"),
        _verdict_check("verdict_gender"),
        _verdict_check("verdict_race"),
        schema="cold_case",
    )


def downgrade() -> None:
    op.drop_table("extraction_review", schema="cold_case")

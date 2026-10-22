"""Add unique index backing case_extractions idempotency.

Revision ID: 0018
Revises: 0017

The extraction worker/CLI guard against duplicate work with a SELECT-then-INSERT
idempotency check on (case_id, prompt_hash, model_id, prompt_tier). That check
was not backed by a DB constraint, so a CLI backfill running alongside the live
worker could both pass the check and double-insert a "current" extraction row
(which then fans out the case_extractions_current join). This adds the unique
index; the inserts use ON CONFLICT DO NOTHING against it. Verified 0 existing
duplicates before adding, so the build is clean.
"""
from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_INDEX = "uq_case_extractions_dedup"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON cold_case.case_extractions
            (case_id, prompt_hash, model_id, prompt_tier)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS cold_case.{_INDEX}")

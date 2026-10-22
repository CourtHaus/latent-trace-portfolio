"""Add cold_case.case_photo.storage_path.

storage_path is the photo file's location relative to the photos root
(CASESIGNAL_PHOTOS_ROOT, default data/photos/), e.g.
`cold_case_oh_ag/3869/00_teaser.aspx.jpg`. It is populated by
scripts/backfill_photo_storage_path.py (a sha256 disk scan) — adapters write
the files; the backfill records where they landed. Nullable: a row whose
file is missing from disk has no storage_path until the file is restored.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "case_photo",
        sa.Column("storage_path", sa.Text(), nullable=True),
        schema="cold_case",
    )


def downgrade() -> None:
    op.drop_column("case_photo", "storage_path", schema="cold_case")

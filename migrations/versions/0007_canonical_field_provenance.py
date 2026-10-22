"""Canonical field provenance — tag values as 'source' or 'tier2'.

Adds nullable TEXT columns alongside each backfillable canonical field,
recording whether the value came from the source publisher or from
Tier-2 LLM extraction. Convention: source column is NULL iff value is NULL.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cold_case.cases
            ADD COLUMN address_source TEXT
                CHECK (address_source IS NULL OR address_source IN ('source', 'tier2')),
            ADD COLUMN incident_date_source TEXT
                CHECK (incident_date_source IS NULL OR incident_date_source IN ('source', 'tier2'))
    """)
    op.execute("""
        ALTER TABLE cold_case.victim
            ADD COLUMN age_source TEXT
                CHECK (age_source IS NULL OR age_source IN ('source', 'tier2')),
            ADD COLUMN gender_source TEXT
                CHECK (gender_source IS NULL OR gender_source IN ('source', 'tier2')),
            ADD COLUMN race_source TEXT
                CHECK (race_source IS NULL OR race_source IN ('source', 'tier2'))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE cold_case.cases DROP COLUMN IF EXISTS address_source")
    op.execute("ALTER TABLE cold_case.cases DROP COLUMN IF EXISTS incident_date_source")
    op.execute("ALTER TABLE cold_case.victim DROP COLUMN IF EXISTS age_source")
    op.execute("ALTER TABLE cold_case.victim DROP COLUMN IF EXISTS gender_source")
    op.execute("ALTER TABLE cold_case.victim DROP COLUMN IF EXISTS race_source")

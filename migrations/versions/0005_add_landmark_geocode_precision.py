"""Add 'landmark' to cold_case.cases.geocode_precision CHECK constraint.

Phase 4.1 landed CO with 50% street-precision; the other 50% fell to
county-centroid because Census couldn't resolve city-only or road-only
addresses. The Google Maps Geocoding API can resolve those (cities,
roads, named landmarks/businesses). Hits with location_type ∈
{ROOFTOP, RANGE_INTERPOLATED} are still 'street'; everything else
Google returns (GEOMETRIC_CENTER for roads, APPROXIMATE for cities)
gets tagged 'landmark' so the frontend can distinguish "we know the
neighborhood" from "we know the address".

revision: 0005
revises: 0004
"""
from __future__ import annotations

from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old constraint (named automatically by Postgres in 0002).
    op.execute(
        """
        ALTER TABLE cold_case.cases
            DROP CONSTRAINT IF EXISTS cases_geocode_precision_check
        """
    )
    op.execute(
        """
        ALTER TABLE cold_case.cases
            ADD CONSTRAINT cases_geocode_precision_check
                CHECK (geocode_precision IS NULL OR geocode_precision IN
                    ('street', 'landmark', 'zip', 'county', 'failed'))
        """
    )


def downgrade() -> None:
    # Demote any 'landmark' rows to 'county' before re-narrowing the constraint.
    op.execute(
        "UPDATE cold_case.cases SET geocode_precision='county'"
        " WHERE geocode_precision='landmark'"
    )
    op.execute(
        """
        ALTER TABLE cold_case.cases
            DROP CONSTRAINT IF EXISTS cases_geocode_precision_check
        """
    )
    op.execute(
        """
        ALTER TABLE cold_case.cases
            ADD CONSTRAINT cases_geocode_precision_check
                CHECK (geocode_precision IS NULL OR geocode_precision IN
                    ('street', 'zip', 'county', 'failed'))
        """
    )

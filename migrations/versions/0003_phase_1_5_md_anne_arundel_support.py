"""Phase 1.5 — Anne Arundel MD support + victim_race extraction.

Adds:
- cold_case.case_extractions: victim_race quintuplet
  (victim_race_text, victim_race_raw_phrase, victim_race_source_start,
   victim_race_source_end, victim_race_low_confidence)
- cold_case.victim.race column (canonical-value backfill target)
- Drop+recreate cold_case.case_extractions_current view to surface the
  new victim_race columns

Existing 75 BCounty Tier-2 rows + 524 VA Tier-1 rows stay correct:
new columns default NULL; their narratives don't state race.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-08
"""
from __future__ import annotations

from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cold_case.case_extractions
            ADD COLUMN victim_race_text TEXT,
            ADD COLUMN victim_race_raw_phrase TEXT,
            ADD COLUMN victim_race_source_start INT,
            ADD COLUMN victim_race_source_end INT,
            ADD COLUMN victim_race_low_confidence BOOLEAN
        """
    )
    op.execute("ALTER TABLE cold_case.victim ADD COLUMN IF NOT EXISTS race TEXT")

    op.execute("DROP VIEW IF EXISTS cold_case.case_extractions_current")
    op.execute(
        """
        CREATE VIEW cold_case.case_extractions_current AS
        SELECT DISTINCT ON (case_id, prompt_tier)
            id,
            case_id,
            prompt_tier,
            extracted_at,
            extractor_version,
            prompt_hash,
            model_id,
            raw_llm_response,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            notes,

            weapon,
            weapon_raw_phrase,
            weapon_source_start,
            weapon_source_end,
            weapon_low_confidence,

            location_type,
            location_type_raw_phrase,
            location_type_source_start,
            location_type_source_end,
            location_type_low_confidence,

            incident_date_text,
            incident_date_raw_phrase,
            incident_date_source_start,
            incident_date_source_end,
            incident_date_low_confidence,

            address_text,
            address_raw_phrase,
            address_source_start,
            address_source_end,
            address_low_confidence,

            victim_age_text,
            victim_age_raw_phrase,
            victim_age_source_start,
            victim_age_source_end,
            victim_age_low_confidence,

            victim_gender_text,
            victim_gender_raw_phrase,
            victim_gender_source_start,
            victim_gender_source_end,
            victim_gender_low_confidence,

            victim_race_text,
            victim_race_raw_phrase,
            victim_race_source_start,
            victim_race_source_end,
            victim_race_low_confidence
        FROM cold_case.case_extractions
        ORDER BY case_id, prompt_tier, extracted_at DESC, id DESC
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS cold_case.case_extractions_current")
    op.execute(
        """
        CREATE VIEW cold_case.case_extractions_current AS
        SELECT DISTINCT ON (case_id, prompt_tier)
            id,
            case_id,
            prompt_tier,
            extracted_at,
            extractor_version,
            prompt_hash,
            model_id,
            raw_llm_response,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            notes,

            weapon, weapon_raw_phrase, weapon_source_start,
            weapon_source_end, weapon_low_confidence,

            location_type, location_type_raw_phrase, location_type_source_start,
            location_type_source_end, location_type_low_confidence,

            incident_date_text, incident_date_raw_phrase,
            incident_date_source_start, incident_date_source_end,
            incident_date_low_confidence,

            address_text, address_raw_phrase, address_source_start,
            address_source_end, address_low_confidence,

            victim_age_text, victim_age_raw_phrase, victim_age_source_start,
            victim_age_source_end, victim_age_low_confidence,

            victim_gender_text, victim_gender_raw_phrase,
            victim_gender_source_start, victim_gender_source_end,
            victim_gender_low_confidence
        FROM cold_case.case_extractions
        ORDER BY case_id, prompt_tier, extracted_at DESC, id DESC
        """
    )

    # Note: cold_case.victim.race is owned by 0001_baseline; this migration's
    # upgrade used ADD COLUMN IF NOT EXISTS because the column was pre-existing.
    # Downgrade does not drop it — that's 0001's responsibility.
    op.execute(
        """
        ALTER TABLE cold_case.case_extractions
            DROP COLUMN victim_race_text,
            DROP COLUMN victim_race_raw_phrase,
            DROP COLUMN victim_race_source_start,
            DROP COLUMN victim_race_source_end,
            DROP COLUMN victim_race_low_confidence
        """
    )

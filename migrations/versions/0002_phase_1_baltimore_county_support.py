"""Phase 1 — Baltimore County MD support.

Adds:
- cold_case.case_photo (per-case photo metadata; 1:N)
- cold_case.geocoding_job (async geocoding queue)
- cold_case.cases.geocode_precision + source_county_fips columns
- cold_case.case_extractions: prompt_tier column + Tier-2 quintuplets
  for incident_date, address, victim_age, victim_gender
- cold_case.extraction_job.prompt_tier column
- Drop+recreate cold_case.case_extractions_current view to surface
  one row per (case_id, prompt_tier) so a case can carry one Tier-1
  row + one Tier-2 row simultaneously

Backfills geocode_precision='street' for existing VA cases that have
lat/lon (street-level coords from VSPCCD).

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08
"""
from __future__ import annotations

from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================
    # cold_case.case_photo
    # ============================================================
    op.execute(
        """
        CREATE TABLE cold_case.case_photo (
            case_photo_id   BIGSERIAL PRIMARY KEY,
            case_id         BIGINT NOT NULL
                REFERENCES cold_case.cases(case_id) ON DELETE CASCADE,
            filename        TEXT NOT NULL,
            content_type    TEXT NOT NULL,
            width           INTEGER,
            height          INTEGER,
            alt_text        TEXT,
            sha256          TEXT NOT NULL,
            is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
            source_url      TEXT,
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (case_id, filename)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_case_photo_case ON cold_case.case_photo(case_id)"
    )

    # ============================================================
    # cold_case.geocoding_job
    # ============================================================
    op.execute(
        """
        CREATE TABLE cold_case.geocoding_job (
            geocoding_job_id    BIGSERIAL PRIMARY KEY,
            case_id             BIGINT NOT NULL
                REFERENCES cold_case.cases(case_id) ON DELETE CASCADE,
            address_text        TEXT NOT NULL,
            state_code          CHAR(2),
            zip_code            TEXT,
            county_fips         TEXT,
            status              TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
            worker_id           TEXT,
            worker_started_at   TIMESTAMPTZ,
            started_at          TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            error_detail        TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CHECK (completed_at IS NULL OR started_at IS NOT NULL),
            CHECK (completed_at IS NULL OR completed_at >= started_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_geocoding_job_queued"
        " ON cold_case.geocoding_job(status, created_at)"
        " WHERE status = 'queued'"
    )
    op.execute(
        "CREATE INDEX ix_geocoding_job_running"
        " ON cold_case.geocoding_job(status, worker_started_at)"
        " WHERE status = 'running'"
    )

    # ============================================================
    # cold_case.cases — geocode_precision + source_county_fips columns
    # ============================================================
    op.execute(
        """
        ALTER TABLE cold_case.cases
            ADD COLUMN geocode_precision TEXT
                CHECK (geocode_precision IS NULL OR geocode_precision IN
                    ('street', 'zip', 'county', 'failed')),
            ADD COLUMN source_county_fips TEXT
        """
    )
    # Backfill: VA cases with non-null lat/lon got street-level coords from
    # VSPCCD; mark them as 'street' precision. Cases without coords stay NULL
    # (geocode_precision = NULL means "never geocoded").
    op.execute(
        "UPDATE cold_case.cases"
        " SET geocode_precision = 'street'"
        " WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    )

    # ============================================================
    # cold_case.case_extractions — prompt_tier + Tier-2 quintuplets
    # ============================================================
    op.execute(
        """
        ALTER TABLE cold_case.case_extractions
            ADD COLUMN prompt_tier SMALLINT NOT NULL DEFAULT 1,

            ADD COLUMN incident_date_text TEXT,
            ADD COLUMN incident_date_raw_phrase TEXT,
            ADD COLUMN incident_date_source_start INT,
            ADD COLUMN incident_date_source_end INT,
            ADD COLUMN incident_date_low_confidence BOOLEAN,

            ADD COLUMN address_text TEXT,
            ADD COLUMN address_raw_phrase TEXT,
            ADD COLUMN address_source_start INT,
            ADD COLUMN address_source_end INT,
            ADD COLUMN address_low_confidence BOOLEAN,

            ADD COLUMN victim_age_text TEXT,
            ADD COLUMN victim_age_raw_phrase TEXT,
            ADD COLUMN victim_age_source_start INT,
            ADD COLUMN victim_age_source_end INT,
            ADD COLUMN victim_age_low_confidence BOOLEAN,

            ADD COLUMN victim_gender_text TEXT,
            ADD COLUMN victim_gender_raw_phrase TEXT,
            ADD COLUMN victim_gender_source_start INT,
            ADD COLUMN victim_gender_source_end INT,
            ADD COLUMN victim_gender_low_confidence BOOLEAN
        """
    )

    # Drop and recreate the case_extractions_current view to surface one row
    # per (case_id, prompt_tier). A case carries one Tier-1 row (existing
    # weapon + location_type) and optionally one Tier-2 row (Phase 1's
    # incident_date + address + victim_age + victim_gender), and the
    # API queries this view to get the latest of each.
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
            victim_gender_low_confidence
        FROM cold_case.case_extractions
        ORDER BY case_id, prompt_tier, extracted_at DESC, id DESC
        """
    )

    # ============================================================
    # cold_case.extraction_job — prompt_tier column for dispatch
    # ============================================================
    op.execute(
        "ALTER TABLE cold_case.extraction_job"
        " ADD COLUMN prompt_tier SMALLINT NOT NULL DEFAULT 1"
    )


def downgrade() -> None:
    # extraction_job
    op.execute(
        "ALTER TABLE cold_case.extraction_job DROP COLUMN prompt_tier"
    )

    # Restore the original view (no prompt_tier, only Tier-1 columns)
    op.execute("DROP VIEW IF EXISTS cold_case.case_extractions_current")
    op.execute(
        """
        CREATE VIEW cold_case.case_extractions_current AS
        SELECT DISTINCT ON (case_id)
            id,
            case_id,
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
            location_type_low_confidence
        FROM cold_case.case_extractions
        ORDER BY case_id, extracted_at DESC, id DESC
        """
    )

    # case_extractions Tier-2 + prompt_tier columns
    op.execute(
        """
        ALTER TABLE cold_case.case_extractions
            DROP COLUMN prompt_tier,
            DROP COLUMN incident_date_text,
            DROP COLUMN incident_date_raw_phrase,
            DROP COLUMN incident_date_source_start,
            DROP COLUMN incident_date_source_end,
            DROP COLUMN incident_date_low_confidence,
            DROP COLUMN address_text,
            DROP COLUMN address_raw_phrase,
            DROP COLUMN address_source_start,
            DROP COLUMN address_source_end,
            DROP COLUMN address_low_confidence,
            DROP COLUMN victim_age_text,
            DROP COLUMN victim_age_raw_phrase,
            DROP COLUMN victim_age_source_start,
            DROP COLUMN victim_age_source_end,
            DROP COLUMN victim_age_low_confidence,
            DROP COLUMN victim_gender_text,
            DROP COLUMN victim_gender_raw_phrase,
            DROP COLUMN victim_gender_source_start,
            DROP COLUMN victim_gender_source_end,
            DROP COLUMN victim_gender_low_confidence
        """
    )

    # cases.geocode_precision + source_county_fips
    op.execute(
        "ALTER TABLE cold_case.cases"
        " DROP COLUMN geocode_precision,"
        " DROP COLUMN source_county_fips"
    )

    # geocoding_job + indexes
    op.execute("DROP TABLE cold_case.geocoding_job")

    # case_photo + index
    op.execute("DROP TABLE cold_case.case_photo")

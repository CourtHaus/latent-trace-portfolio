"""baseline (post-NIBRS demolition)

Squashed from migrations 0001-0018. Creates the final post-refactor
schema for the cold-case-only platform:

- etl.*           framework bookkeeping (renamed from core.*)
- app_auth.api_keys   authentication (HMAC + role + expiry)
- cold_case.*     canonical domain (cases, victim, contact, case_extractions)
- raw_cold_case   empty schema; per-DV tables created lazily by adapters
- audit.*         briefing stub support (read-only; clean rebuild deferred to Phase 4)

NIBRS-domain tables (core.incident*, core.victim, core.offender,
core.agency, core.jurisdiction, raw_nibrs.*, analytics.*, audit.briefing_review_note)
are gone.

PostGIS extension is required.

Revision ID: 0001
Revises:
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- Extensions ------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ----- Schemas ---------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS etl")
    op.execute("CREATE SCHEMA IF NOT EXISTS app_auth")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    op.execute("CREATE SCHEMA IF NOT EXISTS cold_case")
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_cold_case")

    # ======================================================================
    # etl.* — framework bookkeeping (renamed from core.*)
    # ======================================================================

    # etl.source_system
    op.execute(
        """
        CREATE TABLE etl.source_system (
            source_system_id    BIGSERIAL PRIMARY KEY,
            source_code         TEXT NOT NULL UNIQUE,
            source_name         TEXT NOT NULL,
            source_description  TEXT,
            source_url          TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "INSERT INTO etl.source_system (source_code, source_name, source_description)"
        " VALUES ('TEST_CODE', 'Test Source System', 'Used by integration tests.')"
    )

    # etl.dataset_version
    op.execute(
        """
        CREATE TABLE etl.dataset_version (
            dataset_version_id  BIGSERIAL PRIMARY KEY,
            source_system_id    BIGINT NOT NULL
                REFERENCES etl.source_system(source_system_id),
            source_year         INTEGER NOT NULL CHECK (source_year >= 1900 AND source_year <= 2100),
            source_state        TEXT,
            source_label        TEXT NOT NULL,
            source_file_name    TEXT,
            source_release_date DATE,
            source_hash         TEXT,
            ingestion_status    TEXT NOT NULL
                CHECK (ingestion_status IN ('draft', 'validated', 'published', 'failed', 'archived')),
            published_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_dataset_version_source_hash
            ON etl.dataset_version (source_system_id, source_hash)
            WHERE source_hash IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_dataset_version_source_identity_fallback
            ON etl.dataset_version (
                source_system_id,
                source_year,
                COALESCE(source_state, ''),
                COALESCE(source_file_name, ''),
                COALESCE(source_release_date, DATE '0001-01-01')
            )
            WHERE source_hash IS NULL
        """
    )
    op.execute(
        "CREATE INDEX idx_dataset_version_source_file_lookup"
        " ON etl.dataset_version (source_system_id, source_year, source_state, source_file_name)"
    )
    op.execute(
        "CREATE INDEX idx_dataset_version_source_status"
        " ON etl.dataset_version (source_system_id, ingestion_status)"
    )
    op.execute(
        "CREATE INDEX idx_dataset_version_year_state"
        " ON etl.dataset_version (source_year, source_state)"
    )

    # etl.ingestion_run
    op.execute(
        """
        CREATE TABLE etl.ingestion_run (
            ingestion_run_id    BIGSERIAL PRIMARY KEY,
            dataset_version_id  BIGINT NOT NULL
                REFERENCES etl.dataset_version(dataset_version_id),
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at        TIMESTAMPTZ,
            run_status          TEXT NOT NULL
                CHECK (run_status IN ('running', 'succeeded', 'failed', 'partial')),
            rows_read           BIGINT,
            rows_loaded         BIGINT,
            rows_rejected       BIGINT,
            notes               TEXT,
            CHECK (rows_read     IS NULL OR rows_read     >= 0),
            CHECK (rows_loaded   IS NULL OR rows_loaded   >= 0),
            CHECK (rows_rejected IS NULL OR rows_rejected >= 0),
            CHECK (completed_at IS NULL OR completed_at >= started_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ingestion_run_dataset_version"
        " ON etl.ingestion_run (dataset_version_id)"
    )
    op.execute(
        "CREATE INDEX idx_ingestion_run_status_started_at"
        " ON etl.ingestion_run (run_status, started_at DESC)"
    )

    # etl.ingestion_run_stage
    op.execute(
        """
        CREATE TABLE etl.ingestion_run_stage (
            ingestion_run_stage_id  BIGSERIAL PRIMARY KEY,
            ingestion_run_id        BIGINT NOT NULL
                REFERENCES etl.ingestion_run(ingestion_run_id) ON DELETE CASCADE,
            stage_name              TEXT NOT NULL,
            stage_status            TEXT NOT NULL
                CHECK (stage_status IN ('running', 'succeeded', 'failed')),
            started_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at            TIMESTAMPTZ,
            rows_read               BIGINT,
            rows_loaded             BIGINT,
            notes                   TEXT,
            CHECK (rows_read   IS NULL OR rows_read   >= 0),
            CHECK (rows_loaded IS NULL OR rows_loaded >= 0),
            CHECK (completed_at IS NULL OR completed_at >= started_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ingestion_run_stage_ingestion_run"
        " ON etl.ingestion_run_stage (ingestion_run_id)"
    )
    op.execute(
        "CREATE INDEX idx_ingestion_run_stage_run_name_started"
        " ON etl.ingestion_run_stage (ingestion_run_id, stage_name, started_at DESC)"
    )

    # etl.ingestion_job
    op.create_table(
        "ingestion_job",
        sa.Column("ingestion_job_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_definition_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("worker_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("worker_completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "result_ingestion_run_id",
            sa.BigInteger(),
            sa.ForeignKey("etl.ingestion_run.ingestion_run_id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','partial')",
            name="ck_ingestion_job_status",
        ),
        sa.CheckConstraint(
            "worker_completed_at IS NULL OR worker_started_at IS NOT NULL",
            name="ck_ingestion_job_completed_requires_started",
        ),
        sa.CheckConstraint(
            "worker_completed_at IS NULL OR worker_completed_at >= worker_started_at",
            name="ck_ingestion_job_completed_after_started",
        ),
        schema="etl",
    )
    op.execute(
        "CREATE INDEX ingestion_job_queue_idx"
        " ON etl.ingestion_job (created_at)"
        " WHERE status = 'queued'"
    )
    op.execute(
        "CREATE INDEX ingestion_job_running_idx"
        " ON etl.ingestion_job (worker_started_at)"
        " WHERE status = 'running'"
    )

    # ======================================================================
    # app_auth.* — authentication
    # ======================================================================

    op.execute(
        """
        CREATE TABLE app_auth.api_keys (
            key_id        BIGSERIAL PRIMARY KEY,
            key_hash      TEXT,
            label         TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at    TIMESTAMPTZ,
            role          TEXT NOT NULL DEFAULT 'reader'
                          CHECK (role IN ('reader', 'operator', 'admin')),
            expires_at    TIMESTAMPTZ,
            last_used_at  TIMESTAMPTZ,
            key_hmac      TEXT,
            key_prefix    TEXT,
            UNIQUE (key_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_api_keys_key_hmac"
        " ON app_auth.api_keys (key_hmac)"
        " WHERE key_hmac IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_api_keys_key_prefix"
        " ON app_auth.api_keys (key_prefix)"
        " WHERE key_prefix IS NOT NULL"
    )

    # ======================================================================
    # cold_case.* — canonical domain
    # ======================================================================

    # cold_case.cases (with geom generated column)
    op.create_table(
        "cases",
        sa.Column("case_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_version_id",
            sa.Integer(),
            sa.ForeignKey("etl.dataset_version.dataset_version_id"),
            nullable=False,
        ),
        sa.Column("source_case_id", sa.Text(), nullable=False),
        sa.Column("case_name", sa.Text(), nullable=False),
        sa.Column("case_type", sa.Text(), nullable=False),
        sa.Column("incident_date", sa.Date(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.CHAR(2), nullable=False),
        sa.Column("about_text", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "dataset_version_id", "source_case_id", name="uq_cases_dv_source_case_id"
        ),
        sa.UniqueConstraint("slug", name="uq_cases_slug"),
        schema="cold_case",
    )

    # geom generated column (Alembic doesn't emit GENERATED ALWAYS AS .. STORED)
    op.execute(
        """
        ALTER TABLE cold_case.cases ADD COLUMN geom GEOMETRY(POINT, 4326)
            GENERATED ALWAYS AS (
                CASE
                    WHEN latitude IS NOT NULL AND longitude IS NOT NULL
                    THEN ST_SetSRID(ST_MakePoint(longitude::float8, latitude::float8), 4326)
                    ELSE NULL
                END
            ) STORED
        """
    )

    op.execute(
        "CREATE INDEX ix_cases_state_city ON cold_case.cases (state, city)"
    )
    op.execute(
        "CREATE INDEX ix_cases_incident_date ON cold_case.cases (incident_date)"
    )
    op.execute(
        "CREATE INDEX cases_geom_idx ON cold_case.cases USING GIST (geom)"
    )
    # 0018 added a duplicate-named btree index on incident_date; preserved for parity.
    op.execute(
        "CREATE INDEX ix_cold_case_cases_incident_date ON cold_case.cases (incident_date)"
    )

    # cold_case.victim (with age_num generated column)
    op.create_table(
        "victim",
        sa.Column("victim_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "case_id",
            sa.BigInteger(),
            sa.ForeignKey("cold_case.cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("gender", sa.Text(), nullable=True),
        sa.Column("height_text", sa.Text(), nullable=True),
        sa.Column("weight_num", sa.Integer(), nullable=True),
        sa.Column("age_text", sa.Text(), nullable=True),
        sa.Column("race", sa.Text(), nullable=True),
        sa.Column("eye_color", sa.Text(), nullable=True),
        sa.Column("hair_color", sa.Text(), nullable=True),
        schema="cold_case",
    )
    op.execute(
        r"""
        ALTER TABLE cold_case.victim ADD COLUMN age_num INT
            GENERATED ALWAYS AS (
                CASE
                    WHEN age_text ~ '^\s*[0-9]{1,3}\s*$'
                    THEN CAST(trim(age_text) AS INT)
                    ELSE NULL
                END
            ) STORED
        """
    )
    op.execute("CREATE INDEX ix_victim_case_id ON cold_case.victim (case_id)")
    op.execute(
        "CREATE INDEX victim_age_num_idx"
        " ON cold_case.victim (age_num)"
        " WHERE age_num IS NOT NULL"
    )

    # cold_case.contact
    op.create_table(
        "contact",
        sa.Column("contact_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "case_id",
            sa.BigInteger(),
            sa.ForeignKey("cold_case.cases.case_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        schema="cold_case",
    )

    # cold_case.case_extractions + view
    op.execute(
        """
        CREATE TABLE cold_case.case_extractions (
            id               BIGSERIAL PRIMARY KEY,
            case_id          BIGINT NOT NULL REFERENCES cold_case.cases(case_id) ON DELETE CASCADE,
            extracted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            extractor_version TEXT NOT NULL,
            prompt_hash       TEXT NOT NULL,
            model_id          TEXT NOT NULL,
            raw_llm_response  JSONB,
            prompt_tokens     INT,
            completion_tokens INT,
            cost_usd          NUMERIC(10, 6),
            notes             TEXT,

            weapon                TEXT
                CHECK (weapon IS NULL OR weapon IN (
                    'firearm', 'knife', 'blunt', 'personal',
                    'asphyxiation', 'fire', 'other', 'unknown'
                )),
            weapon_raw_phrase     TEXT,
            weapon_source_start   INT,
            weapon_source_end     INT,
            weapon_low_confidence BOOLEAN NOT NULL DEFAULT false,

            location_type                TEXT
                CHECK (location_type IS NULL OR location_type IN (
                    'residence', 'vehicle', 'public_outdoor', 'commercial',
                    'workplace', 'other', 'unknown'
                )),
            location_type_raw_phrase     TEXT,
            location_type_source_start   INT,
            location_type_source_end     INT,
            location_type_low_confidence BOOLEAN NOT NULL DEFAULT false
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_case_extractions_case_latest"
        " ON cold_case.case_extractions (case_id, extracted_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX ix_case_extractions_prompt_model"
        " ON cold_case.case_extractions (prompt_hash, model_id, case_id)"
    )
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

    # cold_case.extraction_job
    op.execute(
        """
        CREATE TABLE cold_case.extraction_job (
            extraction_job_id   BIGSERIAL PRIMARY KEY,
            case_id             BIGINT NOT NULL
                REFERENCES cold_case.cases(case_id) ON DELETE CASCADE,
            prompt_hash         TEXT NOT NULL,
            model_id            TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')),
            worker_id           TEXT,
            worker_started_at   TIMESTAMPTZ,
            worker_completed_at TIMESTAMPTZ,
            error_detail        TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CHECK (worker_completed_at IS NULL OR worker_started_at IS NOT NULL),
            CHECK (worker_completed_at IS NULL OR worker_completed_at >= worker_started_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_extraction_job_queued"
        " ON cold_case.extraction_job (created_at)"
        " WHERE status = 'queued'"
    )
    op.execute(
        "CREATE INDEX idx_extraction_job_running"
        " ON cold_case.extraction_job (worker_started_at)"
        " WHERE status = 'running'"
    )

    # ======================================================================
    # audit.* — briefing stub support (read-only)
    #
    # The /briefings route is preserved as a stub (returns 422 because the
    # contract index is empty), but its handlers SELECT from these tables
    # before the contract check fires. They must exist or queries 500.
    # The schema is reduced to what the stub touches:
    #   - audit.briefing_request (FK target for audit.briefing only)
    #   - audit.briefing
    #   - audit.briefing_tool_execution
    #   - audit.briefing_source_reference
    # NIBRS-era references (core.jurisdiction) are dropped; dataset_version
    # FKs are retargeted to etl.dataset_version. The clean rebuild for the
    # cold-case-oriented analytics chatbot is deferred to Phase 4.
    # ======================================================================

    op.execute(
        """
        CREATE TABLE audit.briefing_request (
            briefing_request_id BIGSERIAL PRIMARY KEY,
            dataset_version_id  BIGINT NOT NULL
                REFERENCES etl.dataset_version(dataset_version_id),
            request_type        TEXT NOT NULL CHECK (request_type IN (
                'jurisdiction_summary',
                'trend_summary',
                'comparison_summary',
                'unresolved_case_overview',
                'custom'
            )),
            user_query          TEXT,
            jurisdiction_id     BIGINT,
            start_date          DATE,
            end_date            DATE,
            filters_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
            requested_by        TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                end_date IS NULL
                OR start_date IS NULL
                OR end_date >= start_date
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE audit.briefing (
            briefing_id            BIGSERIAL PRIMARY KEY,
            briefing_request_id    BIGINT
                REFERENCES audit.briefing_request(briefing_request_id) ON DELETE CASCADE,
            model_name             TEXT,
            status                 TEXT NOT NULL
                CHECK (status IN ('completed', 'partial', 'failed')),
            title                  TEXT,
            summary_text           TEXT,
            structured_output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message          TEXT,
            generated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE audit.briefing_tool_execution (
            briefing_tool_execution_id BIGSERIAL PRIMARY KEY,
            briefing_id                BIGINT NOT NULL
                REFERENCES audit.briefing(briefing_id) ON DELETE CASCADE,
            tool_name                  TEXT NOT NULL,
            execution_order            INTEGER NOT NULL CHECK (execution_order >= 1),
            tool_input_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
            tool_output_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
            success_flag               BOOLEAN NOT NULL DEFAULT TRUE,
            executed_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (briefing_id, execution_order)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE audit.briefing_source_reference (
            briefing_source_reference_id BIGSERIAL PRIMARY KEY,
            briefing_id                  BIGINT NOT NULL
                REFERENCES audit.briefing(briefing_id) ON DELETE CASCADE,
            dataset_version_id           BIGINT NOT NULL
                REFERENCES etl.dataset_version(dataset_version_id),
            entity_type                  TEXT NOT NULL,
            entity_pk                    TEXT,
            section_label                TEXT,
            query_snapshot_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
            citation_text                TEXT,
            created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # audit.ai_briefing — the stub queue table (0005)
    op.execute(
        """
        CREATE TABLE audit.ai_briefing (
            ai_briefing_id      BIGSERIAL PRIMARY KEY,
            retrieval_contract  TEXT NOT NULL,
            filters             JSONB NOT NULL DEFAULT '{}'::jsonb,
            requested_by_key_id BIGINT REFERENCES app_auth.api_keys(key_id),
            status              TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','completed','partial','failed')),
            worker_id           TEXT,
            worker_started_at   TIMESTAMPTZ,
            worker_completed_at TIMESTAMPTZ,
            error_detail        TEXT,
            briefing_id         BIGINT REFERENCES audit.briefing(briefing_id),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_started_when_running CHECK (
                status NOT IN ('running','completed','partial','failed')
                OR worker_started_at IS NOT NULL
            ),
            CONSTRAINT chk_completed_when_terminal CHECK (
                status NOT IN ('completed','partial','failed')
                OR worker_completed_at IS NOT NULL
            ),
            CONSTRAINT chk_briefing_when_completed CHECK (
                status != 'completed'
                OR briefing_id IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ai_briefing_pending"
        " ON audit.ai_briefing (created_at)"
        " WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS raw_cold_case CASCADE")
    op.execute("DROP SCHEMA IF EXISTS cold_case CASCADE")
    op.execute("DROP SCHEMA IF EXISTS audit CASCADE")
    op.execute("DROP SCHEMA IF EXISTS app_auth CASCADE")
    op.execute("DROP SCHEMA IF EXISTS etl CASCADE")
    op.execute("DROP EXTENSION IF EXISTS postgis")

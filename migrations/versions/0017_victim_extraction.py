"""Create cold_case.victim_extraction (per-victim Tier-2 roster).

Revision ID: 0017
Revises: 0016

Holds one row per victim the Tier-2 LLM finds in the narrative, with name +
age + gender each carrying source offsets + low_confidence (mirrors the
case_extractions provenance columns). victim_id is linked by reconciliation.
"""
from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE cold_case.victim_extraction (
            id              bigserial PRIMARY KEY,
            case_id         bigint NOT NULL
                              REFERENCES cold_case.cases(case_id) ON DELETE CASCADE,
            victim_ordinal  int NOT NULL,
            model_id        text NOT NULL,
            prompt_hash     text NOT NULL,
            prompt_tier     int NOT NULL DEFAULT 2,
            extracted_at    timestamptz NOT NULL DEFAULT now(),
            victim_id       bigint
                              REFERENCES cold_case.victim(victim_id) ON DELETE SET NULL,
            name_text             text,
            name_raw_phrase       text,
            name_source_start     int,
            name_source_end       int,
            name_low_confidence   boolean NOT NULL DEFAULT false,
            victim_age_text             text,
            victim_age_raw_phrase       text,
            victim_age_source_start     int,
            victim_age_source_end       int,
            victim_age_low_confidence   boolean NOT NULL DEFAULT false,
            victim_gender_text          text,
            victim_gender_raw_phrase    text,
            victim_gender_source_start  int,
            victim_gender_source_end    int,
            victim_gender_low_confidence boolean NOT NULL DEFAULT false,
            CONSTRAINT uq_victim_extraction_dedup
              UNIQUE (case_id, model_id, prompt_hash, victim_ordinal)
        );
        CREATE INDEX ix_victim_extraction_case ON cold_case.victim_extraction(case_id);
        CREATE INDEX ix_victim_extraction_victim ON cold_case.victim_extraction(victim_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cold_case.victim_extraction")

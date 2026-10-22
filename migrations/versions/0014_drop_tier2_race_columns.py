"""Drop Tier-2 LLM-predicted race columns from case_extractions + extraction_review.

Revision ID: 0014
Revises: 0013

Background
----------
The Tier-2 prompt v2 added ``victim_race`` extraction with extensive guardrails
("don't infer from name", "don't pull from suspect descriptions", etc.). The
model was nevertheless observed deriving race from names and other implicit
cues, which is racist and damaging for a public ViCAP-style platform.

The user policy (memory: feedback-no-llm-race-inference) is that LLM extraction
must never produce race data — no guardrails, no schema, no overlay table. This
migration drops the columns entirely. Source-provided race in ``cold_case.victim``
is unaffected.

The corresponding code changes (Tier-2 v3 prompt, extractor without race fields,
auto-review without race verdicts) ship in the same PR as this migration.

Downgrade restores the columns but cannot restore the data — by design, since
the policy is permanent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


_CASE_EXTRACTIONS_RACE_COLUMNS = (
    "victim_race_text",
    "victim_race_raw_phrase",
    "victim_race_source_start",
    "victim_race_source_end",
    "victim_race_low_confidence",
)

_EXTRACTION_REVIEW_RACE_COLUMNS = (
    "verdict_race",
)


_VIEW_RECREATE_SQL = """
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
        victim_gender_low_confidence{race_columns}
    FROM cold_case.case_extractions
    ORDER BY case_id, prompt_tier, extracted_at DESC, id DESC
"""


def upgrade() -> None:
    # The case_extractions_current view selects the race columns. Drop it,
    # drop the columns, then recreate the view without race.
    op.execute("DROP VIEW IF EXISTS cold_case.case_extractions_current")
    for column in _CASE_EXTRACTIONS_RACE_COLUMNS:
        op.execute(
            f"ALTER TABLE cold_case.case_extractions DROP COLUMN IF EXISTS {column}"
        )
    op.execute(_VIEW_RECREATE_SQL.format(race_columns=""))
    for column in _EXTRACTION_REVIEW_RACE_COLUMNS:
        op.execute(
            f"ALTER TABLE cold_case.extraction_review DROP COLUMN IF EXISTS {column}"
        )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS cold_case.case_extractions_current")
    op.add_column(
        "case_extractions",
        sa.Column("victim_race_text", sa.Text(), nullable=True),
        schema="cold_case",
    )
    op.add_column(
        "case_extractions",
        sa.Column("victim_race_raw_phrase", sa.Text(), nullable=True),
        schema="cold_case",
    )
    op.add_column(
        "case_extractions",
        sa.Column("victim_race_source_start", sa.Integer(), nullable=True),
        schema="cold_case",
    )
    op.add_column(
        "case_extractions",
        sa.Column("victim_race_source_end", sa.Integer(), nullable=True),
        schema="cold_case",
    )
    op.add_column(
        "case_extractions",
        sa.Column("victim_race_low_confidence", sa.Boolean(), nullable=True),
        schema="cold_case",
    )
    op.execute(
        _VIEW_RECREATE_SQL.format(
            race_columns=""",
        victim_race_text,
        victim_race_raw_phrase,
        victim_race_source_start,
        victim_race_source_end,
        victim_race_low_confidence"""
        )
    )
    op.add_column(
        "extraction_review",
        sa.Column("verdict_race", sa.Text(), nullable=True),
        schema="cold_case",
    )

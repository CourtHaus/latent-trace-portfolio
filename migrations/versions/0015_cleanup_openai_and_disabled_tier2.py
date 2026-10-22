"""DB cleanup: delete OpenAI-extracted rows + Tier-2 rows for disabled states.

Revision ID: 0015
Revises: 0014

Background
----------
Phase 1 (PR #138) made local-only LLM extraction project policy and flipped
``DEFAULT_MODEL_ID`` from ``gpt-4o-mini-2024-07-18`` to ``qwen3:14b``. The
methodology page promises "100% local, no case data leaves CaseSignal
hardware" — historically that claim was false because the default model was
OpenAI and ~60% of Tier-1 + ~90% of Tier-2 extractions actually went there.

This migration brings the data in line with the page:

1. Delete every ``case_extractions`` row with ``model_id LIKE 'gpt%'`` —
   the OpenAI-extracted Tier-1 and Tier-2 work.
2. Delete every Tier-2 ``case_extractions`` row for a case in a
   ``TIER2_DISABLED`` state (CO, DC, FL, MN, OH, UT, WY). These states
   provide structured demographics + date + address in their source feeds;
   Tier-2 extraction on them was redundant cost from before the policy
   was wired in (PR #135).
3. Mirror the same deletes in ``cold_case.extraction_job`` so the queue
   history matches the new reality.
4. Delete ``cold_case.extraction_review`` auto-review rows whose
   (case_id, prompt_hash) no longer references a surviving extraction.
   Human-reviewer rows are preserved.

Phase 3 will run ``extract-cold-cases --tier 1`` and ``--tier 2`` against
the cleaned tables to re-extract every case on Qwen3:14b + V3 prompt.

Reversibility
-------------
The OpenAI rows cannot be restored (no upstream archive). Downgrade is a
no-op with a logged warning. Don't run this migration unless you've made
the explicit policy decision to drop OpenAI-derived data.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_TIER2_DISABLED_STATES = ("CO", "DC", "FL", "MN", "OH", "UT", "WY")
_logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()

    _logger.info("0015: deleting OpenAI-extracted case_extractions rows...")
    res = bind.execute(
        text("DELETE FROM cold_case.case_extractions WHERE model_id LIKE 'gpt%'")
    )
    _logger.info("0015: deleted %d OpenAI case_extractions rows", res.rowcount)

    _logger.info(
        "0015: deleting Tier-2 case_extractions for source-demographic states %s...",
        _TIER2_DISABLED_STATES,
    )
    res = bind.execute(
        text(
            """
            DELETE FROM cold_case.case_extractions
             WHERE prompt_tier = 2
               AND case_id IN (
                 SELECT case_id FROM cold_case.cases
                  WHERE state = ANY(ARRAY['CO','DC','FL','MN','OH','UT','WY'])
               )
            """
        )
    )
    _logger.info("0015: deleted %d disabled-state Tier-2 rows", res.rowcount)

    _logger.info("0015: deleting OpenAI extraction_job history...")
    res = bind.execute(
        text("DELETE FROM cold_case.extraction_job WHERE model_id LIKE 'gpt%'")
    )
    _logger.info("0015: deleted %d OpenAI extraction_job rows", res.rowcount)

    _logger.info(
        "0015: deleting Tier-2 extraction_job for disabled states...",
    )
    res = bind.execute(
        text(
            """
            DELETE FROM cold_case.extraction_job
             WHERE prompt_tier = 2
               AND case_id IN (
                 SELECT case_id FROM cold_case.cases
                  WHERE state = ANY(ARRAY['CO','DC','FL','MN','OH','UT','WY'])
               )
            """
        )
    )
    _logger.info("0015: deleted %d disabled-state Tier-2 job rows", res.rowcount)

    _logger.info(
        "0015: deleting orphaned auto-review verdicts (no surviving extraction)..."
    )
    res = bind.execute(
        text(
            """
            DELETE FROM cold_case.extraction_review r
             WHERE r.reviewer = 'auto-review'
               AND NOT EXISTS (
                 SELECT 1 FROM cold_case.case_extractions e
                  WHERE e.case_id = r.case_id
                    AND e.prompt_hash = r.prompt_hash
               )
            """
        )
    )
    _logger.info("0015: deleted %d orphaned auto-review rows", res.rowcount)


def downgrade() -> None:
    _logger.warning(
        "0015 downgrade: OpenAI-extracted rows are NOT restorable. "
        "Migration 0015 is a one-way cleanup; downgrade is a no-op."
    )

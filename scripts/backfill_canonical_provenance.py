"""One-shot data migration: tag existing canonical fields with 'source' or 'tier2'.

Heuristic per field: if a Tier-2 row in case_extractions has an extracted value
that matches the canonical column, tag 'tier2'. Otherwise tag 'source'. NULL
canonical → NULL source.

Run after migration 0007 is applied. Idempotent — safe to re-run; only updates
rows where the source column is currently NULL.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_BACKFILL_SQL = [
    # cases.address
    """
    UPDATE cold_case.cases c SET address_source = CASE
        WHEN c.address IS NULL THEN NULL
        WHEN EXISTS (
            SELECT 1 FROM cold_case.case_extractions e
             WHERE e.case_id = c.case_id AND e.prompt_tier = 2
               AND e.address_text = c.address
        ) THEN 'tier2'
        ELSE 'source'
    END
    WHERE c.address_source IS NULL
    """,
    # cases.incident_date — compare against TEXT representation
    """
    UPDATE cold_case.cases c SET incident_date_source = CASE
        WHEN c.incident_date IS NULL THEN NULL
        WHEN EXISTS (
            SELECT 1 FROM cold_case.case_extractions e
             WHERE e.case_id = c.case_id AND e.prompt_tier = 2
               AND e.incident_date_text = c.incident_date::text
        ) THEN 'tier2'
        ELSE 'source'
    END
    WHERE c.incident_date_source IS NULL
    """,
    # victim.age_text
    """
    UPDATE cold_case.victim v SET age_source = CASE
        WHEN v.age_text IS NULL THEN NULL
        WHEN EXISTS (
            SELECT 1 FROM cold_case.case_extractions e
             WHERE e.case_id = v.case_id AND e.prompt_tier = 2
               AND e.victim_age_text = v.age_text
        ) THEN 'tier2'
        ELSE 'source'
    END
    WHERE v.age_source IS NULL
    """,
    # victim.gender
    """
    UPDATE cold_case.victim v SET gender_source = CASE
        WHEN v.gender IS NULL THEN NULL
        WHEN EXISTS (
            SELECT 1 FROM cold_case.case_extractions e
             WHERE e.case_id = v.case_id AND e.prompt_tier = 2
               AND e.victim_gender_text = v.gender
        ) THEN 'tier2'
        ELSE 'source'
    END
    WHERE v.gender_source IS NULL
    """,
    # victim.race — race extraction was removed from Tier-2 in migration 0014
    # (see feedback-no-llm-race-inference). Any existing race value can only
    # have come from source ingestion; if race_source is NULL on a row with a
    # non-NULL race, it's a source row that pre-dates provenance tagging.
    """
    UPDATE cold_case.victim v SET race_source = CASE
        WHEN v.race IS NULL THEN NULL
        ELSE 'source'
    END
    WHERE v.race_source IS NULL
    """,
]


def run_backfill(engine: Engine) -> None:
    """Apply all 5 UPDATEs in a single transaction."""
    with engine.begin() as conn:
        for sql in _BACKFILL_SQL:
            conn.execute(text(sql))


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    engine = create_engine(url)
    run_backfill(engine)
    print("Provenance backfill complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

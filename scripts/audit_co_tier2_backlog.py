"""Audit + cancel the CO Tier-2 backlog.

CO has structured demographics from CBI — Tier-2's value-add is expected
to be near-zero. This script:

  1. Selects 10 random queued CO Tier-2 jobs.
  2. Prints case_id + canonical-field state + narrative excerpt.
  3. Prompts the operator to run those 10 jobs via the extraction worker.
  4. Prompts for confirmation before bulk-cancelling the rest.

Usage:
  DATABASE_URL=postgresql://... python scripts/audit_co_tier2_backlog.py
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    engine = create_engine(url)

    with engine.connect() as c:
        sample = list(c.execute(text("""
            SELECT j.extraction_job_id, c.case_id, c.case_name,
                   substring(c.about_text from 1 for 300) AS narrative_excerpt,
                   c.incident_date,
                   (SELECT array_agg(age_text || '/' || COALESCE(gender,'?') || '/' || COALESCE(race,'?'))
                    FROM cold_case.victim WHERE case_id = c.case_id) AS demo
            FROM cold_case.extraction_job j
            JOIN cold_case.cases c USING(case_id)
            JOIN etl.dataset_version dv USING(dataset_version_id)
            JOIN etl.source_system ss USING(source_system_id)
            WHERE ss.source_code='CBI_CO_PD'
              AND j.prompt_tier=2 AND j.status='queued'
            ORDER BY random() LIMIT 10
        """)))

    if not sample:
        print("No queued CO Tier-2 jobs found. Nothing to audit.")
        return 0

    print("=== 10-case audit sample (queued CO Tier-2 jobs) ===")
    for s in sample:
        print(f"  case_id={s.case_id} job_id={s.extraction_job_id}")
        print(f"    name: {s.case_name}")
        print(f"    canonical incident_date={s.incident_date} demo={s.demo}")
        print(f"    narrative: {s.narrative_excerpt[:200]}...")
        print()

    job_ids = ",".join(str(s.extraction_job_id) for s in sample)
    print("Now: run the extraction worker for these 10 jobs only.")
    print(f"  Job IDs: {job_ids}")
    print()
    print("  Suggested approach: temporarily mark all OTHER queued CO Tier-2 jobs as")
    print("  'paused' (custom status), run the extraction worker, then revert.")
    print("  Or run a one-off extraction CLI invocation against this specific job set.")
    print()
    print("After running: query cold_case.case_extractions for these 10 case_ids,")
    print("inspect the Tier-2 output, compare against canonical fields shown above.")
    print()
    answer = input("Cancel remaining queued CO Tier-2 jobs (NOT including the 10 above)? [y/N]: ").strip().lower()
    if answer != "y":
        print("Aborted; no rows cancelled.")
        return 0

    with engine.begin() as conn:
        # Exclude the 10 we just sampled — they may have been run by the operator
        result = conn.execute(text("""
            UPDATE cold_case.extraction_job SET
                status='cancelled',
                error_detail='audit confirmed redundant — CBI structured demographics cover canonical fields',
                worker_completed_at=NOW()
            WHERE extraction_job_id IN (
              SELECT j.extraction_job_id FROM cold_case.extraction_job j
              JOIN cold_case.cases c USING(case_id)
              JOIN etl.dataset_version dv USING(dataset_version_id)
              JOIN etl.source_system ss USING(source_system_id)
              WHERE ss.source_code='CBI_CO_PD' AND j.prompt_tier=2 AND j.status='queued'
                AND j.extraction_job_id NOT IN :sample_ids
            )
            RETURNING extraction_job_id
        """).bindparams(sample_ids=tuple(s.extraction_job_id for s in sample)))
        cancelled = result.rowcount
    print(f"Cancelled {cancelled} CO Tier-2 jobs (sample of 10 preserved for review).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

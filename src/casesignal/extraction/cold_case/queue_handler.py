"""Queue handler for cold_case.extraction_job.

Claim pattern matches etl.ingestion_job — FOR UPDATE SKIP LOCKED under
a claim query. Idempotency: before calling extract_case, check if a
matching (case_id, prompt_hash, model_id, prompt_tier) already exists
in case_extractions. If yes, mark the job skipped and return.

Two extraction tiers are dispatched here:
  prompt_tier=1 — Tier-1 (weapon, location_type) classification
  prompt_tier=2 — Tier-2 (incident_date, address, victim_age, victim_gender)

The job's prompt_tier column tells the worker which extractor to invoke.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.extraction.cold_case.extract_case import extract_case
from casesignal.extraction.cold_case.persistence import (
    backfill_canonical_values_from_tier2,
    enqueue_geocoding_job_from_tier2,
    extraction_exists_for,
    insert_extraction,
    insert_tier2_extraction,
    insert_victim_extractions,
)
from casesignal.extraction.cold_case.promote_demographics import (
    promote_victim_demographics,
)
from casesignal.extraction.cold_case.reconcile_victims import (
    apply_reconciliation,
    plan_reconciliation,
)
from casesignal.extraction.cold_case.tier2_extract_case import extract_case_tier2
from casesignal.extraction.cold_case.tier_policy import tier2_enabled_for_state
from casesignal.worker.llm.protocol import LLMClient


class ExtractionFailedError(RuntimeError):
    """The LLM returned an unusable (malformed/empty) response.

    Raised so the job goes through the same failure path as an LLM API error:
    marked 'failed' (re-runnable) with the reason in error_detail, and NOT
    persisted as a successful case_extractions row. Without this, a malformed
    response was saved as a 'succeeded' row that the idempotency check then
    skipped forever.
    """


@dataclass(frozen=True)
class ExtractionJob:
    extraction_job_id: int
    case_id: int
    prompt_hash: str
    model_id: str
    prompt_tier: int


def enqueue_extraction_job(
    session: Session,
    case_id: int,
    prompt_hash: str,
    model_id: str,
    prompt_tier: int = 1,
) -> None:
    """Insert a queued extraction job. Caller controls commit."""
    session.execute(
        text("""
            INSERT INTO cold_case.extraction_job
                (case_id, prompt_hash, model_id, prompt_tier)
            VALUES (:case_id, :prompt_hash, :model_id, :prompt_tier)
        """),
        {
            "case_id": case_id,
            "prompt_hash": prompt_hash,
            "model_id": model_id,
            "prompt_tier": prompt_tier,
        },
    )


_CLAIM_SQL = text("""
    UPDATE cold_case.extraction_job
       SET status = 'running',
           worker_started_at = NOW(),
           worker_id = :worker_id
     WHERE extraction_job_id = (
         SELECT extraction_job_id FROM cold_case.extraction_job
          WHERE status = 'queued'
          ORDER BY created_at
          FOR UPDATE SKIP LOCKED
          LIMIT 1
     )
     RETURNING extraction_job_id, case_id, prompt_hash, model_id, prompt_tier
""")

_CLAIM_SQL_HASH_FILTER = text("""
    UPDATE cold_case.extraction_job
       SET status = 'running',
           worker_started_at = NOW(),
           worker_id = :worker_id
     WHERE extraction_job_id = (
         SELECT extraction_job_id FROM cold_case.extraction_job
          WHERE status = 'queued'
            AND (
                (prompt_tier = 1 AND prompt_hash = :tier1_hash)
             OR (prompt_tier = 2 AND prompt_hash = :tier2_hash)
            )
          ORDER BY created_at
          FOR UPDATE SKIP LOCKED
          LIMIT 1
     )
     RETURNING extraction_job_id, case_id, prompt_hash, model_id, prompt_tier
""")


def claim_next_extraction_job(
    session: Session,
    worker_id: str,
    *,
    tier1_hash: str | None = None,
    tier2_hash: str | None = None,
) -> ExtractionJob | None:
    """Claim the oldest queued job for worker_id. Returns None if queue empty.

    When *tier1_hash* and *tier2_hash* are both provided the claim SQL adds a
    filter so only jobs whose ``(prompt_tier, prompt_hash)`` matches what this
    worker loaded are eligible.  Jobs with a stale hash (e.g. v3 tier-2 jobs
    when a v4 worker is running) are simply never claimed and remain queued
    until a compatible worker or a CLI backfill handles them.

    Both hash parameters must be supplied together; omitting both falls back to
    the original unfiltered behaviour (useful for callers that pre-date hash
    tracking and for existing tests that do not care about hash alignment).
    """
    if tier1_hash is not None and tier2_hash is not None:
        sql = _CLAIM_SQL_HASH_FILTER
        params: dict[str, object] = {
            "worker_id": worker_id,
            "tier1_hash": tier1_hash,
            "tier2_hash": tier2_hash,
        }
    else:
        sql = _CLAIM_SQL
        params = {"worker_id": worker_id}

    row = session.execute(sql, params).first()
    if row is None:
        return None
    session.commit()  # publish the claim so other workers skip this row
    return ExtractionJob(
        extraction_job_id=row.extraction_job_id,
        case_id=row.case_id,
        prompt_hash=row.prompt_hash,
        model_id=row.model_id,
        prompt_tier=row.prompt_tier,
    )


def handle_extraction_job(
    session: Session,
    job: ExtractionJob,
    llm_client: LLMClient,
    tier1_prompt_template: str,
    tier2_prompt_template: str,
    model_id: str,
) -> None:
    """Process a claimed extraction job; dispatches by tier. Caller commits.

    Idempotency: if case_extractions already has a row for
    (case_id, prompt_hash, model_id, prompt_tier), mark the job skipped
    and return without calling the LLM.
    """
    if extraction_exists_for(session, job.case_id, job.prompt_hash, job.model_id, job.prompt_tier):
        session.execute(
            text("""
                UPDATE cold_case.extraction_job
                   SET status = 'skipped',
                       worker_completed_at = NOW()
                 WHERE extraction_job_id = :id
            """),
            {"id": job.extraction_job_id},
        )
        return

    # Fetch about_text + state + source_county_fips (used by Tier-2 post-write
    # geocoding-job enqueue).
    row = session.execute(
        text("""
            SELECT about_text, state, source_county_fips
              FROM cold_case.cases
             WHERE case_id = :cid
        """),
        {"cid": job.case_id},
    ).first()
    if row is None:
        session.execute(
            text("""
                UPDATE cold_case.extraction_job
                   SET status = 'failed',
                       error_detail = 'case_id not found',
                       worker_completed_at = NOW()
                 WHERE extraction_job_id = :id
            """),
            {"id": job.extraction_job_id},
        )
        return

    about_text = row.about_text
    if not about_text:
        session.execute(
            text("""
                UPDATE cold_case.extraction_job
                   SET status = 'failed',
                       error_detail = 'about_text is empty',
                       worker_completed_at = NOW()
                 WHERE extraction_job_id = :id
            """),
            {"id": job.extraction_job_id},
        )
        return

    if job.prompt_tier == 2 and not tier2_enabled_for_state(row.state):
        session.execute(
            text("""
                UPDATE cold_case.extraction_job
                   SET status = 'skipped',
                       error_detail = :err,
                       worker_completed_at = NOW()
                 WHERE extraction_job_id = :id
            """),
            {
                "id": job.extraction_job_id,
                "err": f"tier2 disabled for source-demographic state {row.state}",
            },
        )
        return

    try:
        if job.prompt_tier == 1:
            result = extract_case(
                case_id=job.case_id,
                about_text=about_text,
                llm_client=llm_client,
                prompt_template=tier1_prompt_template,
                model_id=model_id,
            )
            if result.failed:
                raise ExtractionFailedError(result.notes or "tier-1 extraction failed")
            insert_extraction(session, result)
        elif job.prompt_tier == 2:
            tier2_result = extract_case_tier2(
                case_id=job.case_id,
                about_text=about_text,
                llm_client=llm_client,
                prompt_template=tier2_prompt_template,
                model_id=model_id,
            )
            if tier2_result.failed:
                raise ExtractionFailedError(
                    tier2_result.notes or "tier-2 extraction failed"
                )
            insert_tier2_extraction(session, tier2_result)
            backfill_canonical_values_from_tier2(session, tier2_result)
            enqueue_geocoding_job_from_tier2(
                session,
                tier2_result,
                state_code=row.state,
                county_fips=row.source_county_fips,
            )
            # Roster persistence + reconciliation — mirrors cli.py exactly.
            insert_victim_extractions(session, tier2_result)
            victim_rows = session.execute(
                text(
                    "SELECT victim_id, first_name, last_name"
                    " FROM cold_case.victim"
                    " WHERE case_id = :cid"
                    " ORDER BY victim_id"
                ),
                {"cid": job.case_id},
            ).mappings().all()
            existing = [dict(r) for r in victim_rows]
            roster = [
                {"ordinal": v.ordinal, "name": v.name.value}
                for v in tier2_result.victims
            ]
            plan = plan_reconciliation(existing, roster)
            apply_reconciliation(
                session,
                job.case_id,
                plan,
                model_id=tier2_result.model_id,
                prompt_hash=tier2_result.prompt_hash,
            )
            # Phase-2 promotion: fill NULL victim demographics from the
            # roster rows reconciliation just linked. Same transaction.
            promote_victim_demographics(session, case_id=job.case_id)
        else:
            raise ValueError(f"Unknown prompt_tier: {job.prompt_tier}")

        session.execute(
            text("""
                UPDATE cold_case.extraction_job
                   SET status = 'succeeded',
                       worker_completed_at = NOW()
                 WHERE extraction_job_id = :id
            """),
            {"id": job.extraction_job_id},
        )
    except Exception as exc:
        # Roll back any partial extraction insert, then record the failure
        # in its own committed transaction so it survives any rollback the
        # caller (worker loop) does on the original session. Previously
        # this method re-raised after running the UPDATE on `session`, and
        # the worker's `session.rollback()` would wipe the failed-status
        # write — leaving the job stuck in 'running' until 2-hour recovery.
        session.rollback()
        engine = session.get_bind()
        with Session(engine) as recovery:
            recovery.execute(
                text("""
                    UPDATE cold_case.extraction_job
                       SET status = 'failed',
                           error_detail = :err,
                           worker_completed_at = NOW()
                     WHERE extraction_job_id = :id
                """),
                {"id": job.extraction_job_id, "err": str(exc)[:500]},
            )
            recovery.commit()
        # Re-raise so the worker loop logs it; the failed status is already
        # committed in a separate session above, so any rollback the worker
        # does on `session` won't wipe it.
        raise

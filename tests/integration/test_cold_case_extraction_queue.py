"""Integration tests for the queue handler — claim, idempotency, write-path."""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.extraction.cold_case.extract_case import (
    EXTRACTOR_VERSION,
    CaseExtraction,
    ExtractedField,
)
from casesignal.extraction.cold_case.queue_handler import (
    ExtractionFailedError,
    claim_next_extraction_job,
    enqueue_extraction_job,
    handle_extraction_job,
)
from tests.integration._seed import CaseSpec, SeedFn

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(os.environ["DATABASE_URL"])
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        # Park queued ingestion-pipeline jobs so the test's claim picks up
        # ONLY the TEST_HASH job enqueued inside the test body. Restored in
        # the finally block so subsequent runs (or a real worker) still see them.
        # error_detail is used as a marker — distinguishes parked rows from
        # rows legitimately in 'skipped' status (which have error_detail NULL).
        s.execute(
            text(
                "UPDATE cold_case.extraction_job "
                "SET status = 'skipped', error_detail = '__parked_by_test__' "
                "WHERE status = 'queued'"
            )
        )
        s.commit()
        try:
            yield s
        finally:
            s.rollback()
            s.execute(text("DELETE FROM cold_case.extraction_job WHERE prompt_hash LIKE 'TEST_%'"))
            s.execute(
                text("DELETE FROM cold_case.case_extractions WHERE extractor_version LIKE 'TEST_%'")
            )
            s.execute(
                text(
                    "UPDATE cold_case.extraction_job "
                    "SET status = 'queued', error_detail = NULL "
                    "WHERE status = 'skipped' AND error_detail = '__parked_by_test__'"
                )
            )
            s.commit()
    engine.dispose()


def _seed_case(seed: SeedFn, source_code: str, source_case_id: str, *, state: str = "ZZ") -> int:
    corpus = seed(
        source_code,
        [
            CaseSpec(
                source_case_id=source_case_id,
                case_name=f"Extraction Queue Test {source_case_id}",
                state=state,
                city="Queueville",
                about_text="Victim was shot inside a residence.",
            )
        ],
    )
    return int(corpus.case_ids[source_case_id])


def test_enqueue_creates_queued_row(db_session: Session, seed: SeedFn) -> None:
    case_id = _seed_case(seed, "EXTRACTION_QUEUE_ENQUEUE", "xq-enqueue")
    enqueue_extraction_job(
        db_session, case_id=case_id, prompt_hash="TEST_HASH", model_id="TEST_MODEL"
    )
    db_session.commit()
    status = db_session.execute(
        text(
            "SELECT status FROM cold_case.extraction_job WHERE case_id = :cid AND prompt_hash = 'TEST_HASH'"
        ),
        {"cid": case_id},
    ).scalar_one()
    assert status == "queued"


def test_claim_marks_running(db_session: Session, seed: SeedFn) -> None:
    case_id = _seed_case(seed, "EXTRACTION_QUEUE_CLAIM", "xq-claim")
    enqueue_extraction_job(
        db_session, case_id=case_id, prompt_hash="TEST_HASH", model_id="TEST_MODEL"
    )
    db_session.commit()

    claimed = claim_next_extraction_job(db_session, worker_id="worker-1")
    assert claimed is not None
    assert claimed.case_id == case_id
    status = db_session.execute(
        text("SELECT status FROM cold_case.extraction_job WHERE extraction_job_id = :id"),
        {"id": claimed.extraction_job_id},
    ).scalar_one()
    assert status == "running"


def test_handle_job_marks_failed_when_llm_raises(db_session: Session, seed: SeedFn) -> None:
    """An LLM API exception must surface as job status='failed' that survives
    the worker loop's own session.rollback().

    Regression test for PR #73 fallout: extract_case used to swallow LLM
    exceptions and return a marker-field CaseExtraction, so the handler
    marked the job 'succeeded' and the gpt-4.1-mini-vs-gpt-4o-mini 404
    silently corrupted 2,796 OH jobs.
    """
    case_id = _seed_case(seed, "EXTRACTION_QUEUE_FAIL", "xq-fail")
    enqueue_extraction_job(
        db_session,
        case_id=case_id,
        prompt_hash="TEST_HASH_FAIL",
        model_id="TEST_MODEL_FAIL",
    )
    db_session.commit()

    claimed = claim_next_extraction_job(db_session, worker_id="worker-fail")
    assert claimed is not None
    assert claimed.prompt_hash == "TEST_HASH_FAIL"

    boom_llm = MagicMock()
    boom_llm.chat.side_effect = RuntimeError("model not found")

    with pytest.raises(RuntimeError, match="model not found"):
        handle_extraction_job(
            db_session,
            job=claimed,
            llm_client=boom_llm,
            tier1_prompt_template="prompt {about_text}",
            tier2_prompt_template="prompt {about_text}",
            model_id="TEST_MODEL_FAIL",
        )

    # Simulate the worker loop's rollback path. The handler committed the
    # failed status in a separate session, so the rollback here must not
    # affect it.
    db_session.rollback()

    status, error_detail = db_session.execute(
        text(
            "SELECT status, error_detail FROM cold_case.extraction_job"
            " WHERE extraction_job_id = :id"
        ),
        {"id": claimed.extraction_job_id},
    ).one()
    assert status == "failed"
    assert error_detail is not None and "model not found" in error_detail


def test_handle_job_idempotent_on_existing_extraction(db_session: Session, seed: SeedFn) -> None:
    """If an extraction already exists for (case_id, prompt_hash, model_id),
    handle_extraction_job marks the job skipped and does not call the LLM."""
    case_id = _seed_case(seed, "EXTRACTION_QUEUE_IDEMPOTENT", "xq-idempotent")

    # Pre-insert an extraction matching the signature.
    from casesignal.extraction.cold_case.persistence import insert_extraction

    existing = CaseExtraction(
        case_id=case_id,
        weapon=ExtractedField("firearm", "shot", 0, 4, False),
        location_type=ExtractedField("residence", "home", 5, 9, False),
        extractor_version="TEST_" + EXTRACTOR_VERSION,
        prompt_hash="TEST_HASH",
        model_id="TEST_MODEL",
        raw_llm_response={"stub": True},
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.0001,
        notes=None,
    )
    insert_extraction(db_session, existing)

    enqueue_extraction_job(
        db_session, case_id=case_id, prompt_hash="TEST_HASH", model_id="TEST_MODEL"
    )
    db_session.commit()

    claimed = claim_next_extraction_job(db_session, worker_id="worker-1")
    assert claimed is not None

    mock_llm = MagicMock()
    handle_extraction_job(
        db_session,
        job=claimed,
        llm_client=mock_llm,
        tier1_prompt_template="unused",
        tier2_prompt_template="unused",
        model_id="TEST_MODEL",
    )
    db_session.commit()

    # LLM never called because extraction already existed.
    mock_llm.chat.assert_not_called()

    status = db_session.execute(
        text("SELECT status FROM cold_case.extraction_job WHERE extraction_job_id = :id"),
        {"id": claimed.extraction_job_id},
    ).scalar_one()
    assert status == "skipped"


def test_handle_job_skips_tier2_for_disabled_state(db_session: Session, seed: SeedFn) -> None:
    # UT (full source demographics from BCI) stays in the disabled set.
    case_id = _seed_case(seed, "EXTRACTION_QUEUE_TIER2_DISABLED", "xq-ut", state="UT")
    enqueue_extraction_job(
        db_session,
        case_id=case_id,
        prompt_hash="TEST_TIER2_DISABLED",
        model_id="TEST_MODEL",
        prompt_tier=2,
    )
    db_session.commit()

    claimed = claim_next_extraction_job(db_session, worker_id="worker-tier2-disabled")
    assert claimed is not None
    assert claimed.prompt_tier == 2

    mock_llm = MagicMock()
    handle_extraction_job(
        db_session,
        job=claimed,
        llm_client=mock_llm,
        tier1_prompt_template="unused",
        tier2_prompt_template="unused",
        model_id="TEST_MODEL",
    )
    db_session.commit()

    mock_llm.chat.assert_not_called()
    status, error_detail = db_session.execute(
        text(
            "SELECT status, error_detail FROM cold_case.extraction_job "
            "WHERE extraction_job_id = :id"
        ),
        {"id": claimed.extraction_job_id},
    ).one()
    assert status == "skipped"
    assert error_detail == "tier2 disabled for source-demographic state UT"


def test_claim_hash_filter_skips_stale_hash(db_session: Session, seed: SeedFn) -> None:
    """A v4 worker must claim only the job whose prompt_hash matches v4 and
    must never claim a stale-hash (v3) tier-2 job.

    Two queued tier-2 jobs are inserted:
      - one with a hash the worker recognises (V4_HASH)
      - one with a stale hash the worker does not recognise (V3_STALE_HASH)

    claim_next_extraction_job called with tier2_hash='TEST_V4_HASH' must
    return the V4 job and leave the stale job in 'queued' status.
    """
    v4_case_id = _seed_case(seed, "EXTRACTION_QUEUE_V4", "xq-hash-v4")
    stale_case_id = _seed_case(seed, "EXTRACTION_QUEUE_STALE", "xq-hash-stale")

    # Enqueue the v4-hash job first (oldest created_at) so an unfiltered claim
    # would pick it; the stale job is second.
    enqueue_extraction_job(
        db_session,
        case_id=v4_case_id,
        prompt_hash="TEST_V4_HASH",
        model_id="TEST_MODEL",
        prompt_tier=2,
    )
    enqueue_extraction_job(
        db_session,
        case_id=stale_case_id,
        prompt_hash="TEST_V3_STALE_HASH",
        model_id="TEST_MODEL",
        prompt_tier=2,
    )
    db_session.commit()

    # Worker presents v4 hashes for both tiers.
    claimed = claim_next_extraction_job(
        db_session,
        worker_id="worker-hash-filter",
        tier1_hash="TEST_TIER1_HASH",
        tier2_hash="TEST_V4_HASH",
    )

    assert claimed is not None, "expected to claim the v4-hash job"
    assert claimed.prompt_hash == "TEST_V4_HASH"
    assert claimed.case_id == v4_case_id

    # The stale job must still be queued — never touched by this worker.
    stale_status = db_session.execute(
        text(
            "SELECT status FROM cold_case.extraction_job"
            " WHERE case_id = :cid AND prompt_hash = 'TEST_V3_STALE_HASH'"
        ),
        {"cid": stale_case_id},
    ).scalar_one()
    assert stale_status == "queued", (
        f"stale-hash job should remain queued, got {stale_status!r}"
    )


def _malformed_llm() -> MagicMock:
    """A mock LLM whose response drives extract_case down the malformed path
    (no tool_calls, content isn't parseable extraction JSON)."""
    turn = MagicMock()
    turn.finish_reason = "stop"
    turn.malformed_reason = "unparseable content"
    turn.assistant_message.content = "I cannot help with that."
    turn.assistant_message.tool_calls = None
    llm = MagicMock()
    llm.chat.return_value = turn
    return llm


def test_handle_job_malformed_tier1_fails_and_persists_no_row(
    db_session: Session, seed: SeedFn
) -> None:
    """A malformed LLM response must mark the job 'failed' (re-runnable) and
    persist NO case_extractions row — not a 'succeeded' row that the idempotency
    check then skips forever."""
    case_id = _seed_case(seed, "EXTRACTION_QUEUE_MALFORMED1", "xq-malf1")
    enqueue_extraction_job(
        db_session, case_id=case_id, prompt_hash="TEST_HASH_MALF1", model_id="TEST_MODEL"
    )
    db_session.commit()

    claimed = claim_next_extraction_job(db_session, worker_id="worker-malf1")
    assert claimed is not None

    with pytest.raises(ExtractionFailedError):
        handle_extraction_job(
            db_session,
            job=claimed,
            llm_client=_malformed_llm(),
            tier1_prompt_template="prompt {about_text}",
            tier2_prompt_template="prompt {about_text}",
            model_id="TEST_MODEL",
        )
    db_session.rollback()  # simulate the worker loop's rollback

    status, error_detail = db_session.execute(
        text(
            "SELECT status, error_detail FROM cold_case.extraction_job"
            " WHERE extraction_job_id = :id"
        ),
        {"id": claimed.extraction_job_id},
    ).one()
    assert status == "failed"
    assert error_detail is not None and "Malformed" in error_detail

    row_count = db_session.execute(
        text("SELECT count(*) FROM cold_case.case_extractions WHERE case_id = :cid"),
        {"cid": case_id},
    ).scalar_one()
    assert row_count == 0, "malformed extraction must not be persisted"


def test_handle_job_malformed_tier2_fails_and_persists_no_row(
    db_session: Session, seed: SeedFn
) -> None:
    """Same guarantee for Tier-2: malformed → failed job, no row. (Tier-2's
    'value=None' also means 'not stated', so the fix keys on the explicit
    failed flag, not on all-fields-None.)"""
    case_id = _seed_case(seed, "EXTRACTION_QUEUE_MALFORMED2", "xq-malf2")  # state ZZ → tier2 enabled
    enqueue_extraction_job(
        db_session,
        case_id=case_id,
        prompt_hash="TEST_HASH_MALF2",
        model_id="TEST_MODEL",
        prompt_tier=2,
    )
    db_session.commit()

    claimed = claim_next_extraction_job(db_session, worker_id="worker-malf2")
    assert claimed is not None
    assert claimed.prompt_tier == 2

    with pytest.raises(ExtractionFailedError):
        handle_extraction_job(
            db_session,
            job=claimed,
            llm_client=_malformed_llm(),
            tier1_prompt_template="prompt {about_text}",
            tier2_prompt_template="prompt {about_text}",
            model_id="TEST_MODEL",
        )
    db_session.rollback()

    status = db_session.execute(
        text("SELECT status FROM cold_case.extraction_job WHERE extraction_job_id = :id"),
        {"id": claimed.extraction_job_id},
    ).scalar_one()
    assert status == "failed"

    row_count = db_session.execute(
        text("SELECT count(*) FROM cold_case.case_extractions WHERE case_id = :cid"),
        {"cid": case_id},
    ).scalar_one()
    assert row_count == 0


def test_insert_extraction_dedup_on_conflict(db_session: Session, seed: SeedFn) -> None:
    """The unique index (migration 0018) + ON CONFLICT DO NOTHING make a
    double-insert of the same (case_id, prompt_hash, model_id, tier) a no-op
    rather than a second 'current' row that fans out the join."""
    from casesignal.extraction.cold_case.persistence import insert_extraction

    case_id = _seed_case(seed, "EXTRACTION_QUEUE_CONFLICT", "xq-conflict")
    ext = CaseExtraction(
        case_id=case_id,
        weapon=ExtractedField("firearm", "shot", 0, 4, False),
        location_type=ExtractedField("residence", "home", 5, 9, False),
        extractor_version="TEST_" + EXTRACTOR_VERSION,
        prompt_hash="TEST_HASH_CONFLICT",
        model_id="TEST_MODEL",
        raw_llm_response={"stub": True},
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=0.0,
        notes=None,
    )
    insert_extraction(db_session, ext)
    insert_extraction(db_session, ext)  # second must no-op, not error or duplicate
    db_session.commit()

    count = db_session.execute(
        text(
            "SELECT count(*) FROM cold_case.case_extractions"
            " WHERE case_id = :cid AND prompt_hash = 'TEST_HASH_CONFLICT'"
        ),
        {"cid": case_id},
    ).scalar_one()
    assert count == 1


def test_claim_hash_filter_returns_none_when_only_stale_jobs_queued(
    db_session: Session, seed: SeedFn
) -> None:
    """When the only queued jobs have a stale hash, the worker's hash-filtered
    claim must return None (queue appears empty to this worker)."""
    stale_case_id = _seed_case(seed, "EXTRACTION_QUEUE_STALE_ONLY", "xq-stale-only")
    enqueue_extraction_job(
        db_session,
        case_id=stale_case_id,
        prompt_hash="TEST_V3_STALE_HASH_ONLY",
        model_id="TEST_MODEL",
        prompt_tier=2,
    )
    db_session.commit()

    claimed = claim_next_extraction_job(
        db_session,
        worker_id="worker-hash-filter-empty",
        tier1_hash="TEST_TIER1_HASH",
        tier2_hash="TEST_V4_HASH_ONLY",
    )

    assert claimed is None, "expected None when all queued jobs have a stale hash"

    # Stale job must still be queued.
    stale_status = db_session.execute(
        text(
            "SELECT status FROM cold_case.extraction_job"
            " WHERE case_id = :cid AND prompt_hash = 'TEST_V3_STALE_HASH_ONLY'"
        ),
        {"cid": stale_case_id},
    ).scalar_one()
    assert stale_status == "queued"

"""Long-running worker that claims and processes cold_case.extraction_job.

Parallels worker/ingestion_loop.py:
  - signal handling (SIGTERM → shutdown after current job)
  - stuck-worker recovery on startup
  - claim via FOR UPDATE SKIP LOCKED
  - idle sleep when queue is empty

Entry point: `casesignal-extraction-worker` (added to pyproject.toml).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from typing import Any

logger = logging.getLogger(__name__)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
    load_tier2_v4_prompt_template,
)
from casesignal.extraction.cold_case.queue_handler import (
    claim_next_extraction_job,
    handle_extraction_job,
)
from casesignal.observability import init_sentry, worker_heartbeat
from casesignal.worker.llm.factory import make_llm_client

WORKER_ID = f"extraction-{socket.gethostname()}-{os.getpid()}"
IDLE_SLEEP_SECONDS = 5
STUCK_WORKER_HOURS = 2


_shutdown = False


def _on_sigterm(signum: int, frame: Any) -> None:  # noqa: ARG001
    global _shutdown
    _shutdown = True


_RECOVERY_SQL = text(
    "UPDATE cold_case.extraction_job"
    " SET status='failed',"
    "     error_detail='worker crash recovery',"
    "     worker_completed_at=NOW()"
    " WHERE status='running'"
    f"   AND worker_started_at < NOW() - INTERVAL '{STUCK_WORKER_HOURS} hours'"
)


def run_extraction_worker_loop() -> None:
    """Main entry point — loop claiming and processing jobs."""
    init_sentry("extraction-worker")
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, _on_sigterm)

    engine = create_engine(os.environ["DATABASE_URL"])
    Session = sessionmaker(engine)

    tier1_template = load_tier1_prompt_template()
    tier2_template = load_tier2_v4_prompt_template()
    tier1_hash = compute_prompt_hash(tier1_template)
    tier2_hash = compute_prompt_hash(tier2_template)
    pinned_model = get_pinned_model_id()
    llm_client = make_llm_client(model_id=pinned_model)

    # Stuck-worker recovery on startup
    with Session() as s:
        s.execute(_RECOVERY_SQL)
        s.commit()

    logger.info(
        "extraction worker started worker_id=%s model=%s tier1_hash=%s tier2_hash=%s",
        WORKER_ID, pinned_model, tier1_hash[:8], tier2_hash[:8],
    )

    while not _shutdown:
        # Dead-man's-switch: throttled check-in to the Sentry cron monitor.
        # If a job hangs (e.g. wedged LLM backend), the next check-in never
        # lands and the monitor alerts after its grace margin.
        worker_heartbeat()
        with Session() as session:
            job = claim_next_extraction_job(
                session,
                worker_id=WORKER_ID,
                tier1_hash=tier1_hash,
                tier2_hash=tier2_hash,
            )
            if job is None:
                time.sleep(IDLE_SLEEP_SECONDS)
                continue
            try:
                handle_extraction_job(
                    session,
                    job,
                    llm_client=llm_client,
                    tier1_prompt_template=tier1_template,
                    tier2_prompt_template=tier2_template,
                    model_id=pinned_model,
                )
                session.commit()
                logger.info(
                    "processed tier-%d job worker_id=%s job_id=%s case_id=%s",
                    job.prompt_tier, WORKER_ID, job.extraction_job_id, job.case_id,
                )
            except Exception:
                session.rollback()
                logger.exception(
                    "extraction job failed worker_id=%s job_id=%s",
                    WORKER_ID, job.extraction_job_id,
                )

    logger.info("extraction worker shutdown complete worker_id=%s", WORKER_ID)
    engine.dispose()

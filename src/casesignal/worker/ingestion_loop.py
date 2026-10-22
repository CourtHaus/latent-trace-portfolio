from __future__ import annotations

import json
import logging
import os
import signal
import socket
import time
from typing import Any

logger = logging.getLogger(__name__)

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.api.routes.admin.ingestion import IngestionRunRequest
from casesignal.api.services.ingestion import IngestionAdminService
from casesignal.etl.runners.run_pipeline import run_source_definition
from casesignal.observability import init_sentry

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


_CLAIM_SQL = text(
    "UPDATE etl.ingestion_job"
    " SET status='running',"
    "     worker_started_at=NOW(),"
    "     worker_id=:worker_id"
    " WHERE ingestion_job_id = ("
    "   SELECT ingestion_job_id FROM etl.ingestion_job"
    "   WHERE status='queued'"
    "   ORDER BY created_at"
    "   FOR UPDATE SKIP LOCKED"
    "   LIMIT 1"
    " )"
    " RETURNING ingestion_job_id, source_definition_json"
)


_RECOVERY_SQL = text(
    "UPDATE etl.ingestion_job"
    " SET status='failed',"
    "     error_detail='worker crash recovery',"
    "     worker_completed_at=NOW()"
    " WHERE status='running'"
    "   AND worker_started_at < NOW() - INTERVAL '2 hours'"
)


_shutdown = False


def _on_sigterm(signum: int, frame: Any) -> None:
    global _shutdown
    _shutdown = True


def claim_next_job(session: Session) -> dict[str, Any] | None:
    # The UPDATE already holds the row lock via FOR UPDATE SKIP LOCKED; the
    # commit releases so a concurrent worker can claim the NEXT queued row.
    row = session.execute(_CLAIM_SQL, {"worker_id": WORKER_ID}).fetchone()
    if row is None:
        return None
    session.commit()
    payload = row.source_definition_json
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {
        "ingestion_job_id": row.ingestion_job_id,
        "source_definition_json": payload,
    }


def run_crash_recovery(session: Session) -> None:
    session.execute(_RECOVERY_SQL)
    session.commit()


def execute_job(
    job: dict[str, Any],
    session: Session,
    service: IngestionAdminService,
) -> None:
    request = IngestionRunRequest.model_validate(job["source_definition_json"])
    try:
        source_definition = service.build_source_definition(request)
        result = run_source_definition(source_definition)
        session.execute(
            text(
                "UPDATE etl.ingestion_job"
                " SET status=:s,"
                "     result_ingestion_run_id=:rid,"
                "     worker_completed_at=NOW()"
                " WHERE ingestion_job_id=:jid"
            ),
            {
                "s": result.run_status,
                "rid": result.ingestion_run_id,
                "jid": job["ingestion_job_id"],
            },
        )
    except Exception as exc:
        # Log (→ a Sentry event via the logging integration) so handled job
        # failures are visible, not just silently marked failed in the DB.
        logger.exception(
            "ingestion job failed ingestion_job_id=%s", job["ingestion_job_id"]
        )
        session.execute(
            text(
                "UPDATE etl.ingestion_job"
                " SET status='failed',"
                "     error_detail=:e,"
                "     worker_completed_at=NOW()"
                " WHERE ingestion_job_id=:jid"
            ),
            {
                "e": str(exc)[:1000],
                "jid": job["ingestion_job_id"],
            },
        )
    session.commit()


def run_ingestion_worker_loop() -> None:
    """Entry point: poll etl.ingestion_job, execute claimed jobs sequentially."""
    from casesignal.api.dependencies.db import get_engine

    init_sentry("ingestion-worker")
    signal.signal(signal.SIGTERM, _on_sigterm)

    engine = get_engine()
    SessionLocal = sessionmaker(engine)
    service = IngestionAdminService()

    with SessionLocal() as session:
        run_crash_recovery(session)

    logger.info("ingestion worker started worker_id=%s, polling for jobs", WORKER_ID)

    while not _shutdown:
        with SessionLocal() as session:
            job = claim_next_job(session)

        if job is None:
            for _ in range(5):
                if _shutdown:
                    break
                time.sleep(1)
            continue

        logger.info("claimed ingestion job_id=%s", job["ingestion_job_id"])
        try:
            with SessionLocal() as session:
                execute_job(job, session, service)
        except Exception:
            logger.exception(
                "unhandled error processing ingestion job_id=%s",
                job["ingestion_job_id"],
            )
        logger.info("finished ingestion job_id=%s", job["ingestion_job_id"])

    logger.info("ingestion worker shutting down cleanly worker_id=%s (SIGTERM)", WORKER_ID)

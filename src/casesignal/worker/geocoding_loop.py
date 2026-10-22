"""Async geocoding worker.

Polls cold_case.geocoding_job for queued jobs, runs each through the
GeocodingService ladder (Census street → ZIP centroid → county centroid →
'failed'), writes lat/lon + geocode_precision back to cold_case.cases,
and marks the job complete.

Mirrors worker/ingestion_loop.py for queue mechanics: FOR UPDATE SKIP
LOCKED claim, 2-hour stuck-worker recovery on startup, SIGTERM graceful
shutdown.

Console script: casesignal-geocoding-worker (registered in pyproject.toml).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.geocoding.service import (
    GeocodingJobInput,
    GeocodingService,
)
from casesignal.observability import init_sentry

logger = logging.getLogger(__name__)


WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


_CLAIM_SQL = text(
    "UPDATE cold_case.geocoding_job"
    " SET status='running',"
    "     worker_started_at=NOW(),"
    "     started_at=NOW(),"
    "     worker_id=:worker_id"
    " WHERE geocoding_job_id = ("
    "   SELECT geocoding_job_id FROM cold_case.geocoding_job"
    "   WHERE status='queued'"
    "   ORDER BY created_at"
    "   FOR UPDATE SKIP LOCKED"
    "   LIMIT 1"
    " )"
    " RETURNING geocoding_job_id, case_id, address_text, state_code,"
    "           zip_code, county_fips"
)


_RECOVERY_SQL = text(
    "UPDATE cold_case.geocoding_job"
    " SET status='failed',"
    "     error_detail='worker crash recovery',"
    "     started_at=COALESCE(started_at, worker_started_at),"
    "     completed_at=NOW()"
    " WHERE status='running'"
    "   AND worker_started_at < NOW() - INTERVAL '2 hours'"
)


_shutdown = False


def _on_sigterm(signum: int, frame: Any) -> None:
    global _shutdown
    _shutdown = True


def claim_next_job(session: Session) -> dict[str, Any] | None:
    """Atomically claim one queued job. Returns None if queue is empty."""
    row = session.execute(_CLAIM_SQL, {"worker_id": WORKER_ID}).fetchone()
    if row is None:
        return None
    session.commit()
    return {
        "geocoding_job_id": row.geocoding_job_id,
        "case_id": row.case_id,
        "address_text": row.address_text,
        "state_code": row.state_code,
        "zip_code": row.zip_code,
        "county_fips": row.county_fips,
    }


def run_crash_recovery(session: Session) -> None:
    """Mark any 'running' jobs older than 2 hours as failed (worker died)."""
    session.execute(_RECOVERY_SQL)
    session.commit()


def execute_job(
    job: dict[str, Any],
    session: Session,
    service: GeocodingService,
) -> None:
    """Run the geocoding ladder, write results to cases + job rows."""
    job_input = GeocodingJobInput(
        address_text=job["address_text"],
        state_code=job.get("state_code"),
        zip_code=job.get("zip_code"),
        county_fips=job.get("county_fips"),
    )

    try:
        result = service.geocode_for_job(job_input)

        # Write coordinates + precision back to the case row. We only update
        # lat/lon when the worker found *something* (any tier above 'failed').
        # Cases with precision='failed' keep lat/lon=NULL, so the map filter
        # naturally excludes them.
        if result.latitude is not None and result.longitude is not None:
            session.execute(
                text(
                    "UPDATE cold_case.cases"
                    " SET latitude=:lat,"
                    "     longitude=:lon,"
                    "     geocode_precision=:precision"
                    " WHERE case_id=:cid"
                ),
                {
                    "lat": result.latitude,
                    "lon": result.longitude,
                    "precision": result.precision,
                    "cid": job["case_id"],
                },
            )
        else:
            session.execute(
                text(
                    "UPDATE cold_case.cases"
                    " SET geocode_precision=:precision"
                    " WHERE case_id=:cid"
                ),
                {
                    "precision": result.precision,
                    "cid": job["case_id"],
                },
            )

        session.execute(
            text(
                "UPDATE cold_case.geocoding_job"
                " SET status='succeeded',"
                "     completed_at=NOW(),"
                "     error_detail=:notes"
                " WHERE geocoding_job_id=:jid"
            ),
            {
                "notes": result.notes,
                "jid": job["geocoding_job_id"],
            },
        )
    except Exception as exc:
        # Log (→ a Sentry event via the logging integration) so handled job
        # failures are visible, not just silently marked failed in the DB.
        logger.exception(
            "geocoding job failed geocoding_job_id=%s", job["geocoding_job_id"]
        )
        session.execute(
            text(
                "UPDATE cold_case.geocoding_job"
                " SET status='failed',"
                "     error_detail=:e,"
                "     completed_at=NOW()"
                " WHERE geocoding_job_id=:jid"
            ),
            {
                "e": str(exc)[:1000],
                "jid": job["geocoding_job_id"],
            },
        )
    session.commit()


def run_geocoding_worker_loop() -> None:
    """Entry point: poll cold_case.geocoding_job and process claimed jobs.

    Constructs a single GeocodingService (which holds a single httpx client
    for Census API connection reuse) and a single sessionmaker; both are
    reused across many job iterations.
    """
    from casesignal.api.dependencies.db import get_engine

    init_sentry("geocoding-worker")
    signal.signal(signal.SIGTERM, _on_sigterm)

    engine = get_engine()
    SessionLocal = sessionmaker(engine)
    service = GeocodingService()

    try:
        with SessionLocal() as session:
            run_crash_recovery(session)

        logger.info("geocoding worker started worker_id=%s, polling for jobs", WORKER_ID)

        while not _shutdown:
            with SessionLocal() as session:
                job = claim_next_job(session)

            if job is None:
                # Idle — sleep in 1s slices so SIGTERM lands quickly.
                for _ in range(5):
                    if _shutdown:
                        break
                    time.sleep(1)
                continue

            logger.info(
                "claimed geocoding job_id=%s case_id=%s",
                job["geocoding_job_id"], job["case_id"],
            )
            try:
                with SessionLocal() as session:
                    execute_job(job, session, service)
            except Exception:
                logger.exception(
                    "unhandled error processing geocoding job_id=%s",
                    job["geocoding_job_id"],
                )
            logger.info("finished geocoding job_id=%s", job["geocoding_job_id"])

        logger.info("geocoding worker shutting down cleanly worker_id=%s (SIGTERM)", WORKER_ID)
    finally:
        service.close()

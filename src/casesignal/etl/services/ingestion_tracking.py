from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.services.pipeline_context import PipelineContext

STAGE_INSERT_SQL = text("""
    INSERT INTO etl.ingestion_run_stage (
        ingestion_run_id,
        stage_name,
        stage_status,
        started_at,
        completed_at,
        rows_read,
        rows_loaded,
        notes
    )
    VALUES (
        :ingestion_run_id,
        :stage_name,
        :stage_status,
        :started_at,
        :completed_at,
        :rows_read,
        :rows_loaded,
        :notes
    )
    RETURNING ingestion_run_stage_id
    """)

STAGE_UPDATE_SQL = text("""
    UPDATE etl.ingestion_run_stage
    SET
        stage_status = :stage_status,
        completed_at = :completed_at,
        rows_read = :rows_read,
        rows_loaded = :rows_loaded,
        notes = :notes
    WHERE ingestion_run_stage_id = :ingestion_run_stage_id
    """)

INGESTION_RUN_COUNTERS_UPDATE_SQL = text("""
    UPDATE etl.ingestion_run
    SET
        rows_read = :rows_read,
        rows_loaded = :rows_loaded
    WHERE ingestion_run_id = :ingestion_run_id
    """)

INGESTION_RUN_FAILED_SQL = text("""
    UPDATE etl.ingestion_run
    SET
        run_status = 'failed',
        completed_at = COALESCE(completed_at, NOW()),
        rows_read = :rows_read,
        rows_loaded = :rows_loaded,
        notes = :notes
    WHERE ingestion_run_id = :ingestion_run_id
    """)

DATASET_VERSION_FAILED_SQL = text("""
    UPDATE etl.dataset_version
    SET ingestion_status = CASE
        WHEN ingestion_status = 'published' THEN ingestion_status
        ELSE 'failed'
    END
    WHERE dataset_version_id = :dataset_version_id
    """)


def record_stage_start(
    context: PipelineContext,
    stage_name: str,
    started_at: datetime,
) -> int | None:
    if context.ingestion_run_id is None:
        return None

    session_factory = _require_session_factory(context)

    with session_factory() as session:
        stage_id = session.execute(
            STAGE_INSERT_SQL,
            {
                "ingestion_run_id": context.ingestion_run_id,
                "stage_name": stage_name,
                "stage_status": "running",
                "started_at": started_at,
                "completed_at": None,
                "rows_read": None,
                "rows_loaded": None,
                "notes": None,
            },
        ).scalar_one()
        session.commit()

    return int(stage_id)


def record_stage_finish(
    context: PipelineContext,
    stage_record_id: int | None,
    stage_name: str,
    started_at: datetime,
    completed_at: datetime,
    stage_status: str,
    rows_loaded: int | None = None,
    notes: str | None = None,
) -> None:
    if context.ingestion_run_id is None:
        return

    session_factory = _require_session_factory(context)
    total_rows = context.total_row_count

    with session_factory() as session:
        if stage_record_id is None:
            session.execute(
                STAGE_INSERT_SQL,
                {
                    "ingestion_run_id": context.ingestion_run_id,
                    "stage_name": stage_name,
                    "stage_status": stage_status,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "rows_read": rows_loaded,
                    "rows_loaded": rows_loaded,
                    "notes": notes,
                },
            )
        else:
            session.execute(
                STAGE_UPDATE_SQL,
                {
                    "ingestion_run_stage_id": stage_record_id,
                    "stage_status": stage_status,
                    "completed_at": completed_at,
                    "rows_read": rows_loaded,
                    "rows_loaded": rows_loaded,
                    "notes": notes,
                },
            )

        session.execute(
            INGESTION_RUN_COUNTERS_UPDATE_SQL,
            {
                "ingestion_run_id": context.ingestion_run_id,
                "rows_read": total_rows,
                "rows_loaded": total_rows,
            },
        )
        session.commit()


def mark_ingestion_run_failed(context: PipelineContext, error_message: str) -> None:
    if context.ingestion_run_id is None or context.dataset_version_id is None:
        return

    session_factory = _require_session_factory(context)
    total_rows = context.total_row_count
    failure_note = _truncate_notes(f"Pipeline failed: {error_message}")

    with session_factory() as session:
        session.execute(
            INGESTION_RUN_FAILED_SQL,
            {
                "ingestion_run_id": context.ingestion_run_id,
                "rows_read": total_rows,
                "rows_loaded": total_rows,
                "notes": failure_note,
            },
        )
        session.execute(
            DATASET_VERSION_FAILED_SQL,
            {
                "dataset_version_id": context.dataset_version_id,
            },
        )
        session.commit()


def _require_session_factory(context: PipelineContext) -> sessionmaker[Session]:
    session_factory = context.get_metadata("session_factory")
    if session_factory is None:
        raise ValueError("session_factory is not available in pipeline context metadata.")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError(
            "session_factory in pipeline context metadata is not a SQLAlchemy sessionmaker."
        )
    return session_factory


def _truncate_notes(notes: str, max_length: int = 2000) -> str:
    if len(notes) <= max_length:
        return notes
    return f"{notes[: max_length - 3]}..."

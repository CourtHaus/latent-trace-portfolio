from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.services.pipeline_context import PipelineContext


def publish_dataset(context: PipelineContext) -> None:
    """
    Finalize a successful pipeline execution for any source family.

    Responsibilities:
    - mark the current ingestion_run as completed successfully
    - mark the dataset_version as ready for downstream use
    - record a simple completion note

    This stage should not perform transformation or derivation logic.
    """
    logger = context.logger
    assert logger is not None

    dataset_version_id = context.require_dataset_version_id()
    ingestion_run_id = context.require_ingestion_run_id()
    session_factory = _require_session_factory(context)

    with session_factory() as session:
        try:
            _mark_ingestion_run_completed(
                session=session,
                ingestion_run_id=ingestion_run_id,
                rows_loaded=context.total_row_count,
                source_key=context.source_key,
            )
            _mark_dataset_version_published(
                session=session,
                dataset_version_id=dataset_version_id,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    logger.info(
        "Published dataset_version_id=%s for ingestion_run_id=%s.",
        dataset_version_id,
        ingestion_run_id,
    )


def _require_session_factory(context: PipelineContext) -> sessionmaker[Session]:
    session_factory = context.get_metadata("session_factory")
    if session_factory is None:
        raise ValueError("session_factory is not available in pipeline context metadata.")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError(
            "session_factory in pipeline context metadata is not a SQLAlchemy sessionmaker."
        )
    return session_factory


def _mark_ingestion_run_completed(
    session: Session, ingestion_run_id: int, rows_loaded: int, source_key: str
) -> None:
    """
    Mark the ingestion run as successfully completed.
    """
    result = session.execute(
        text("""
            UPDATE etl.ingestion_run
            SET
                run_status = :run_status,
                completed_at = NOW(),
                rows_read = :rows_read,
                rows_loaded = :rows_loaded,
                notes = :notes
            WHERE ingestion_run_id = :ingestion_run_id
            """),
        {
            "ingestion_run_id": ingestion_run_id,
            "run_status": "succeeded",
            "rows_read": rows_loaded,
            "rows_loaded": rows_loaded,
            "notes": f"Pipeline completed successfully for source_key={source_key}. rows_loaded={rows_loaded}",
        },
    )

    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise RuntimeError(
            f"Expected to update exactly one ingestion_run row for ingestion_run_id={ingestion_run_id}, "
            f"but updated {result.rowcount} row(s)."  # type: ignore[attr-defined]
        )


def _mark_dataset_version_published(session: Session, dataset_version_id: int) -> None:
    """Mark the dataset version as published, archiving the prior published
    version OF THE SAME SLICE.

    A re-ingest creates a NEW dataset_version whenever the source_hash changes.
    Publishing the new one WITHOUT archiving the previous published version of
    the same slice leaves two 'published' versions live at once, which the
    public queries (gated only on ingestion_status='published') double-count.

    A "slice" is identified by (source_system_id, source_label), NOT just the
    source_system. One source can intentionally publish multiple slices at once
    — e.g. DC MPDC publishes a 2020 slice and a 1951–2019 slice under the same
    source_code, with distinct source_labels. Archiving by source_system alone
    would wrongly retire a live sibling slice (half the DC corpus). source_label
    is set per source-definition entry and is stable across re-ingests, so it is
    the durable per-slice identity (the reuse key is source_hash, which changes
    every re-ingest and so cannot identify the lineage).
    """
    # Archive the prior published version of the SAME slice (same source_system
    # AND same source_label), leaving sibling slices of this source untouched.
    session.execute(
        text("""
            UPDATE etl.dataset_version d
            SET ingestion_status = 'archived'
            FROM etl.dataset_version cur
            WHERE cur.dataset_version_id = :dataset_version_id
              AND d.source_system_id = cur.source_system_id
              AND d.source_label = cur.source_label
              AND d.dataset_version_id != cur.dataset_version_id
              AND d.ingestion_status = 'published'
            """),
        {"dataset_version_id": dataset_version_id},
    )

    result = session.execute(
        text("""
            UPDATE etl.dataset_version
            SET
                ingestion_status = :ingestion_status,
                published_at = NOW()
            WHERE dataset_version_id = :dataset_version_id
            """),
        {
            "dataset_version_id": dataset_version_id,
            "ingestion_status": "published",
        },
    )

    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise RuntimeError(
            f"Expected to update exactly one dataset_version row for dataset_version_id={dataset_version_id}, "
            f"but updated {result.rowcount} row(s)."  # type: ignore[attr-defined]
        )

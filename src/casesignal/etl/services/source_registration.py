"""Shared source registration for scraped cold-case adapters.

Creates (or reuses) the ``source_system`` + ``dataset_version`` +
``ingestion_run`` rows for a cold-case source. Every scraped adapter previously
carried a near-identical ~186-line copy of this logic; the only per-adapter
inputs are the content ``source_hash`` (the adapter computes it from its own
parsed input) and the canonical source URL.

File-based adapters (VA, WY) use a different fingerprint-based registration
(``source_fingerprint.resolve_source_hash`` + a year/state/file fallback) and do
NOT use this helper.

The dataset_version is reused when an existing row matches
``(source_system_id, source_hash)`` — so a re-scrape with unchanged content
returns the same version, and a content change creates a new one. ``draft``
status; publishing happens later via ``dataset_publishing``.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_fingerprint import resolve_source_hash

_SOURCE_SYSTEM_SELECT_SQL = text(
    "SELECT source_system_id FROM etl.source_system WHERE source_code = :source_code"
)
_SOURCE_SYSTEM_INSERT_SQL = text("""
    INSERT INTO etl.source_system (source_code, source_name, source_description, source_url)
    VALUES (:source_code, :source_name, :source_description, :source_url)
    RETURNING source_system_id
""")
_DATASET_VERSION_SELECT_SQL = text("""
    SELECT dataset_version_id
    FROM etl.dataset_version
    WHERE source_system_id = :source_system_id AND source_hash = :source_hash
""")
_DATASET_VERSION_INSERT_SQL = text("""
    INSERT INTO etl.dataset_version (
        source_system_id, source_year, source_state, source_label,
        source_file_name, source_release_date, source_hash, ingestion_status
    )
    VALUES (
        :source_system_id, :source_year, :source_state, :source_label,
        :source_file_name, :source_release_date, :source_hash, :ingestion_status
    )
    RETURNING dataset_version_id
""")
_INGESTION_RUN_INSERT_SQL = text("""
    INSERT INTO etl.ingestion_run (dataset_version_id, run_status, notes)
    VALUES (:dataset_version_id, :run_status, :notes)
    RETURNING ingestion_run_id
""")

# File-based path only: fallback lookup + identity backfill (see
# register_file_based_cold_case_source).
_DATASET_VERSION_SELECT_FALLBACK_SQL = text("""
    SELECT dataset_version_id, source_hash, source_release_date
    FROM etl.dataset_version
    WHERE source_system_id = :source_system_id
      AND source_year = :source_year
      AND source_state IS NOT DISTINCT FROM :source_state
      AND source_file_name IS NOT DISTINCT FROM :source_file_name
    ORDER BY dataset_version_id DESC
    LIMIT 1
""")
_DATASET_VERSION_UPDATE_IDENTITY_SQL = text("""
    UPDATE etl.dataset_version
    SET source_hash = COALESCE(:source_hash, source_hash),
        source_release_date = COALESCE(:source_release_date, source_release_date),
        source_file_name = COALESCE(:source_file_name, source_file_name)
    WHERE dataset_version_id = :dataset_version_id
""")


def register_cold_case_source(
    context: PipelineContext,
    *,
    source_hash: str,
    source_file_name: str | None,
    log_label: str,
) -> None:
    """Register a scraped cold-case source on the pipeline context.

    Args:
        context: pipeline context (provides source_code/name/year/state/label,
            the session_factory + source_definition metadata, and logger).
        source_hash: content fingerprint the adapter computed from its parsed
            input; identical content -> same dataset_version.
        source_file_name: the canonical source URL stored on dataset_version.
        log_label: short human label for the log line + ingestion_run note.

    Sets ``context.source_system_id`` / ``dataset_version_id`` /
    ``ingestion_run_id``. Caller's adapter retains its own hash function.
    """
    logger = context.logger
    if logger is None:
        raise RuntimeError("PipelineContext.logger must be set before running stages.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    source_definition = context.get_metadata("source_definition", {})
    description = source_definition.get("description")
    metadata = source_definition.get("metadata", {})
    source_url = metadata.get("source_url")
    source_release_date = metadata.get("source_release_date")

    with session_factory() as session:
        try:
            source_system_id = _get_or_create_source_system(
                session,
                source_code=context.source_code,
                source_name=context.source_name,
                source_description=description,
                source_url=source_url,
            )
            dataset_version_id = _get_or_create_dataset_version(
                session,
                source_system_id=source_system_id,
                source_year=context.source_year,
                source_state=context.source_state,
                source_label=context.source_label,
                source_file_name=source_file_name,
                source_release_date=source_release_date,
                source_hash=source_hash,
            )
            ingestion_run_id = _create_ingestion_run(
                session,
                dataset_version_id,
                notes=f"{log_label} ingestion run initialized.",
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    context.source_system_id = source_system_id
    context.dataset_version_id = dataset_version_id
    context.ingestion_run_id = ingestion_run_id
    logger.info(
        "Registered %s source. source_system_id=%s, dataset_version_id=%s,"
        " ingestion_run_id=%s, source_hash=%s",
        log_label,
        source_system_id,
        dataset_version_id,
        ingestion_run_id,
        source_hash[:8],
    )


def _get_or_create_source_system(
    session: Session,
    *,
    source_code: str,
    source_name: str,
    source_description: str | None,
    source_url: str | None,
) -> int:
    existing = session.execute(_SOURCE_SYSTEM_SELECT_SQL, {"source_code": source_code}).first()
    if existing is not None:
        return int(existing.source_system_id)
    inserted = session.execute(
        _SOURCE_SYSTEM_INSERT_SQL,
        {
            "source_code": source_code,
            "source_name": source_name,
            "source_description": source_description,
            "source_url": source_url,
        },
    ).first()
    if inserted is None:
        raise RuntimeError(f"Failed to insert source_system for '{source_code}'.")
    return int(inserted.source_system_id)


def _get_or_create_dataset_version(
    session: Session,
    *,
    source_system_id: int,
    source_year: int | None,
    source_state: str | None,
    source_label: str,
    source_file_name: str | None,
    source_release_date: str | None,
    source_hash: str,
) -> int:
    existing = session.execute(
        _DATASET_VERSION_SELECT_SQL,
        {"source_system_id": source_system_id, "source_hash": source_hash},
    ).first()
    if existing is not None:
        return int(existing.dataset_version_id)
    inserted = session.execute(
        _DATASET_VERSION_INSERT_SQL,
        {
            "source_system_id": source_system_id,
            "source_year": source_year,
            "source_state": source_state,
            "source_label": source_label,
            "source_file_name": source_file_name,
            "source_release_date": source_release_date,
            "source_hash": source_hash,
            "ingestion_status": "draft",
        },
    ).first()
    if inserted is None:
        raise RuntimeError(
            f"Failed to insert dataset_version for source_system_id={source_system_id}."
        )
    return int(inserted.dataset_version_id)


def _create_ingestion_run(session: Session, dataset_version_id: int, *, notes: str) -> int:
    inserted = session.execute(
        _INGESTION_RUN_INSERT_SQL,
        {
            "dataset_version_id": dataset_version_id,
            "run_status": "running",
            "notes": notes,
        },
    ).first()
    if inserted is None:
        raise RuntimeError(f"Failed to create ingestion_run for {dataset_version_id}.")
    return int(inserted.ingestion_run_id)


def register_file_based_cold_case_source(
    context: PipelineContext,
    *,
    log_label: str,
    source_file_name: str | None = None,
) -> None:
    """Register a FILE-BASED cold-case source (VA, WY, MN).

    The content fingerprint comes from the input FILE via resolve_source_hash()
    rather than being passed in. The dataset_version lookup adds, on top of the
    by-hash check, a fallback by (source_year, source_state, source_file_name)
    plus an identity backfill — so a version registered before its hash was
    available gets reused and hash-stamped instead of duplicated (VA's original
    contract; a no-op for sources whose hash is always present, like MN).

    source_file_name defaults to the input file's name; pass an override for
    adapters that record a source URL there instead (e.g. WY).
    """
    logger = context.logger
    if logger is None:
        raise RuntimeError("PipelineContext.logger must be set before running stages.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    source_definition = context.get_metadata("source_definition", {})
    metadata = source_definition.get("metadata", {}) or {}
    description = source_definition.get("description")
    source_url = metadata.get("source_url")
    source_release_date = metadata.get("source_release_date")
    source_hash = resolve_source_hash(context.source_path, metadata)
    file_name = (
        source_file_name if source_file_name is not None else context.source_path.name
    )

    with session_factory() as session:
        try:
            source_system_id = _get_or_create_source_system(
                session,
                source_code=context.source_code,
                source_name=context.source_name,
                source_description=description,
                source_url=source_url,
            )
            dataset_version_id = _get_or_create_file_based_dataset_version(
                session,
                source_system_id=source_system_id,
                source_year=context.source_year,
                source_state=context.source_state,
                source_label=context.source_label,
                source_file_name=file_name,
                source_release_date=source_release_date,
                source_hash=source_hash,
                source_key=context.source_key,
            )
            ingestion_run_id = _create_ingestion_run(
                session,
                dataset_version_id,
                notes=f"{log_label} ingestion run initialized.",
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    context.source_system_id = source_system_id
    context.dataset_version_id = dataset_version_id
    context.ingestion_run_id = ingestion_run_id
    logger.info(
        "Registered %s source. source_system_id=%s, dataset_version_id=%s,"
        " ingestion_run_id=%s, source_hash=%s",
        log_label,
        source_system_id,
        dataset_version_id,
        ingestion_run_id,
        (source_hash or "none")[:8],
    )


def _get_or_create_file_based_dataset_version(
    session: Session,
    *,
    source_system_id: int,
    source_year: int | None,
    source_state: str | None,
    source_label: str,
    source_file_name: str | None,
    source_release_date: str | None,
    source_hash: str | None,
    source_key: str,
) -> int:
    if source_hash is not None:
        existing = session.execute(
            _DATASET_VERSION_SELECT_SQL,
            {"source_system_id": source_system_id, "source_hash": source_hash},
        ).first()
        if existing is not None:
            return int(existing.dataset_version_id)

    fallback = session.execute(
        _DATASET_VERSION_SELECT_FALLBACK_SQL,
        {
            "source_system_id": source_system_id,
            "source_year": source_year,
            "source_state": source_state,
            "source_file_name": source_file_name,
        },
    ).first()
    if fallback is not None:
        dataset_version_id = int(fallback.dataset_version_id)
        if source_hash is not None and fallback.source_hash is None:
            # Backfill the identity onto the pre-hash row and REUSE it. Must
            # return here: falling through would INSERT a second row with the
            # same (source_system_id, source_hash), violating
            # uq_dataset_version_source_hash (the read `fallback.source_hash` is
            # the stale NULL from before this UPDATE, so the equality check below
            # can't catch it).
            session.execute(
                _DATASET_VERSION_UPDATE_IDENTITY_SQL,
                {
                    "dataset_version_id": dataset_version_id,
                    "source_hash": source_hash,
                    "source_release_date": source_release_date,
                    "source_file_name": source_file_name,
                },
            )
            return dataset_version_id
        if source_hash is None or fallback.source_hash == source_hash:
            return dataset_version_id

    inserted = session.execute(
        _DATASET_VERSION_INSERT_SQL,
        {
            "source_system_id": source_system_id,
            "source_year": source_year,
            "source_state": source_state,
            "source_label": source_label,
            "source_file_name": source_file_name,
            "source_release_date": source_release_date,
            "source_hash": source_hash,
            "ingestion_status": "draft",
        },
    ).first()
    if inserted is None:
        raise RuntimeError(f"Failed to insert dataset_version for '{source_key}'.")
    return int(inserted.dataset_version_id)

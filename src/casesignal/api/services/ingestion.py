from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.runners.run_pipeline import (
    DEFAULT_CATALOG_PATH,
    resolve_source_definition,
)
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)

SOURCE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

# Resolved at module import time so the containment check is stable across
# process cwd changes.  .resolve() always returns an absolute path, so no
# explicit is_absolute() assertion is needed.
_UPLOAD_ROOT = Path(os.environ.get("INGESTION_UPLOAD_ROOT", "data/raw/uploads")).resolve()


class IngestionAdminService:
    def __init__(
        self,
        upload_root: Path | str | None = None,
        catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    ) -> None:
        self.upload_root = Path(upload_root).resolve() if upload_root is not None else _UPLOAD_ROOT
        self.catalog_path = Path(catalog_path)

    def stage_upload(
        self,
        *,
        content: bytes,
        source_key: str,
        source_code: str,
        source_name: str,
        source_year: int,
        source_state: str | None,
        input_type: str,
    ) -> dict[str, Any]:
        safe_source_key = _validate_source_key(source_key)
        if input_type != "zip":
            raise ValueError("Only zip uploads are supported.")
        if not content:
            raise ValueError("Upload body cannot be empty.")

        staged_dir = self.upload_root / safe_source_key
        staged_dir.mkdir(parents=True, exist_ok=True)
        staged_path = staged_dir / f"{safe_source_key}.zip"
        staged_path.write_bytes(content)

        return {
            "source_key": safe_source_key,
            "source_code": source_code.strip().upper(),
            "source_name": source_name.strip(),
            "source_year": source_year,
            "source_state": source_state.strip().upper() if source_state else None,
            "input_type": input_type,
            "staged_path": str(staged_path),
            "size_bytes": len(content),
        }

    def trigger_run(self, request: Any, session: Session) -> dict[str, Any]:
        # Fail-fast validation: raise 422 (ValueError/KeyError) here, not later in the worker.
        self.build_source_definition(request)

        payload = request.model_dump(mode="json")
        row = session.execute(
            text(
                "INSERT INTO etl.ingestion_job (status, source_definition_json)"
                " VALUES ('queued', CAST(:payload AS JSONB))"
                " RETURNING ingestion_job_id"
            ),
            {"payload": json.dumps(payload)},
        ).fetchone()
        session.commit()
        assert row is not None, "INSERT ... RETURNING must produce a row"
        return {
            "source_key": request.source_key,
            "ingestion_job_id": row.ingestion_job_id,
            "status": "queued",
        }

    def get_run_status(self, session: Session, ingestion_run_id: int) -> dict[str, Any]:
        run_row = session.execute(
            text("""
                SELECT
                    ingestion_run_id,
                    dataset_version_id,
                    run_status,
                    started_at,
                    completed_at,
                    rows_read,
                    rows_loaded,
                    rows_rejected,
                    notes
                FROM etl.ingestion_run
                WHERE ingestion_run_id = :ingestion_run_id
                """),
            {"ingestion_run_id": ingestion_run_id},
        ).fetchone()

        if run_row is None:
            raise KeyError("Ingestion run not found.")

        stage_rows = session.execute(
            text("""
                SELECT
                    ingestion_run_stage_id,
                    stage_name,
                    stage_status,
                    started_at,
                    completed_at,
                    rows_read,
                    rows_loaded,
                    notes
                FROM etl.ingestion_run_stage
                WHERE ingestion_run_id = :ingestion_run_id
                ORDER BY started_at, ingestion_run_stage_id
                """),
            {"ingestion_run_id": ingestion_run_id},
        ).fetchall()

        return {
            **_row_to_dict(run_row),
            "stages": [_row_to_dict(row) for row in stage_rows],
        }

    def get_job_status(self, session: Session, ingestion_job_id: int) -> dict[str, Any]:
        row = session.execute(
            text("""
                SELECT
                    ingestion_job_id,
                    status,
                    created_at,
                    worker_id,
                    worker_started_at,
                    worker_completed_at,
                    error_detail,
                    result_ingestion_run_id AS ingestion_run_id
                FROM etl.ingestion_job
                WHERE ingestion_job_id = :ingestion_job_id
                """),
            {"ingestion_job_id": ingestion_job_id},
        ).fetchone()
        if row is None:
            raise KeyError("Ingestion job not found.")
        return _row_to_dict(row)

    def publish_dataset_version(self, session: Session, dataset_version_id: int) -> dict[str, Any]:
        row = session.execute(
            text("""
                UPDATE etl.dataset_version
                SET
                    ingestion_status = 'published',
                    published_at = NOW()
                WHERE dataset_version_id = :dataset_version_id
                RETURNING dataset_version_id, ingestion_status, published_at
                """),
            {"dataset_version_id": dataset_version_id},
        ).fetchone()
        session.commit()

        if row is None:
            raise KeyError("Dataset version not found.")
        return _row_to_dict(row)

    def unpublish_dataset_version(
        self, session: Session, dataset_version_id: int
    ) -> dict[str, Any]:
        row = session.execute(
            text("""
                UPDATE etl.dataset_version
                SET
                    ingestion_status = 'archived',
                    published_at = NULL
                WHERE dataset_version_id = :dataset_version_id
                RETURNING dataset_version_id, ingestion_status, published_at
                """),
            {"dataset_version_id": dataset_version_id},
        ).fetchone()
        session.commit()

        if row is None:
            raise KeyError("Dataset version not found.")
        return _row_to_dict(row)

    def build_source_definition(self, request: Any) -> SourceDefinition:
        if request.input_path is None:
            return resolve_source_definition(request.source_key, self.catalog_path)

        if (
            request.source_code is None
            or request.source_name is None
            or request.source_year is None
        ):
            raise ValueError(
                "source_code, source_name, and source_year are required when input_path is provided."
            )

        resolved = Path(request.input_path).resolve()
        if not resolved.is_relative_to(self.upload_root):
            # SEC-B06: log the specifics server-side; return a generic message so
            # the response doesn't leak the upload-root path/layout to the caller.
            logger.warning(
                "Rejected ingestion input_path outside upload root: resolved=%s root=%s",
                resolved,
                self.upload_root,
            )
            raise ValueError("input_path is not an allowed location.")

        return SourceDefinition(
            source_key=_validate_source_key(request.source_key),
            source_family=request.source_family,
            adapter_name=request.adapter_name,
            source_code=request.source_code.strip().upper(),
            source_name=request.source_name.strip(),
            input_path=resolved,
            input_type=request.input_type,
            source_year=request.source_year,
            source_state=request.source_state.strip().upper() if request.source_state else None,
            required_files=frozenset(request.required_files or ()),
            optional_files=frozenset(request.optional_files or ()),
            description=request.description,
            metadata=request.metadata or {},
        )


def _validate_source_key(source_key: str) -> str:
    safe_source_key = source_key.strip()
    if not safe_source_key:
        raise ValueError("source_key cannot be blank.")
    if not SOURCE_KEY_PATTERN.fullmatch(safe_source_key):
        raise ValueError("source_key may contain only letters, numbers, underscore, dash, and dot.")
    return safe_source_key


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(vars(row))

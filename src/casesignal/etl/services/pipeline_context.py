from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PipelineContext:
    """
    Shared runtime context for a single ETL pipeline execution.

    This object carries source metadata, filesystem paths, database handles,
    lifecycle identifiers, and runtime metadata across pipeline stages.

    Design notes:
    - The context is intentionally lightweight and procedural.
    - It should contain shared state, not transformation logic.
    - Stage functions should accept PipelineContext rather than large
      collections of positional arguments.
    """

    # -------------------------------------------------------------------------
    # Source metadata
    # -------------------------------------------------------------------------

    source_key: str
    source_code: str
    source_name: str
    source_family: str | None
    source_year: int | None
    source_state: str | None

    # -------------------------------------------------------------------------
    # Filesystem paths
    # -------------------------------------------------------------------------
    source_path: Path
    extracted_path: Path | None = None

    # -------------------------------------------------------------------------
    # Database handles
    # -------------------------------------------------------------------------
    engine: Any | None = None
    session: Any | None = None

    # -------------------------------------------------------------------------
    # Lifecycle identifiers
    # -------------------------------------------------------------------------
    source_system_id: int | None = None
    dataset_version_id: int | None = None
    ingestion_run_id: int | None = None

    # -------------------------------------------------------------------------
    # Runtime metadata
    # -------------------------------------------------------------------------
    logger: logging.Logger | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    row_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.source_path = Path(self.source_path)

        if self.extracted_path is not None:
            self.extracted_path = Path(self.extracted_path)

        if self.logger is None:
            self.logger = logging.getLogger(__name__)

    @property
    def source_label(self) -> str:
        """
        Human-readable dataset label used for logging and dataset registration.
        """
        if self.source_state:
            return f"{self.source_name} {self.source_state} {self.source_year}"
        return f"{self.source_name} {self.source_year}"

    def require_dataset_version_id(self) -> int:
        """
        Return the dataset version ID or raise if it has not been set.
        """
        if self.dataset_version_id is None:
            raise ValueError("dataset_version_id is not set on PipelineContext.")
        return self.dataset_version_id

    def require_ingestion_run_id(self) -> int:
        """
        Return the ingestion run ID or raise if it has not been set.
        """
        if self.ingestion_run_id is None:
            raise ValueError("ingestion_run_id is not set on PipelineContext.")
        return self.ingestion_run_id

    def require_engine(self) -> Any:
        """
        Return the database session or raise if it has not been set.
        """
        if self.engine is None:
            raise ValueError("engine is not set on PipelineContext.")
        return self.engine

    def increment_row_count(self, key: str, amount: int) -> None:
        """
        Increment a named row-count metric.
        """
        if amount < 0:
            raise ValueError("Row count increment amount must be non-negative.")
        self.row_counts[key] = self.row_counts.get(key, 0) + amount

    @property
    def total_row_count(self) -> int:
        return sum(self.row_counts.values())

    def add_error(self, message: str) -> None:
        """
        Record a pipeline error and emit it to the logger.
        """
        self.errors.append(message)
        assert self.logger is not None, "__post_init__ guarantees a logger"
        self.logger.error(message)

    def set_metadata(self, key: str, value: Any) -> None:
        """
        Store arbitrary runtime metadata for the current pipeline execution.
        """
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        Retrieve runtime metadata by key.
        """
        return self.metadata.get(key, default)

    def to_log_dict(self) -> dict[str, Any]:
        """
        Return a structured summary suitable for logging.
        """
        return {
            "source_key": self.source_key,
            "source_family": self.source_family,
            "source_code": self.source_code,
            "source_name": self.source_name,
            "source_year": self.source_year,
            "source_state": self.source_state,
            "source_label": self.source_label,
            "source_path": str(self.source_path),
            "extracted_path": str(self.extracted_path) if self.extracted_path else None,
            "source_system_id": self.source_system_id,
            "dataset_version_id": self.dataset_version_id,
            "ingestion_run_id": self.ingestion_run_id,
            "started_at": self.started_at.isoformat(),
            "row_counts": self.row_counts,
            "row_total": self.total_row_count,
            "warning_count": len(self.warnings),
            "error_count": len(self.errors),
        }

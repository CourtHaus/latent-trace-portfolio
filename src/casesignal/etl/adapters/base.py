"""SourceAdapter — base class for cold-case ingestion adapters.

Five-stage contract:
    prepare_input  →  register_source  →  load_raw  →  transform  →  publish

The run_stage helper handles per-stage logging and etl.ingestion_run_stage
audit-trail rows (renamed to etl.ingestion_run_stage in a later phase).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from casesignal.etl.services.ingestion_tracking import (
    record_stage_finish,
    record_stage_start,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_definition import SourceDefinition


class SourceAdapter(ABC):
    """Base class for cold-case ingestion adapters.

    Concrete adapters override the five stage methods. The default `publish`
    implementation marks the dataset_version as published via the shared
    helper — adapters override only for source-specific finalization.
    """

    def __init__(self, source_definition: SourceDefinition) -> None:
        self.source_definition = source_definition

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Stable adapter identifier used for registration and resolution."""
        raise NotImplementedError

    @abstractmethod
    def prepare_input(self, context: PipelineContext) -> None:
        """Validate source input is reachable/readable; stash paths on context."""
        raise NotImplementedError

    @abstractmethod
    def register_source(self, context: PipelineContext) -> None:
        """Insert/lookup source_system + dataset_version + ingestion_run rows."""
        raise NotImplementedError

    @abstractmethod
    def load_raw(self, context: PipelineContext) -> None:
        """Write source data verbatim to raw_cold_case.<adapter>_dv<N>.

        Format-specific (CSV reader, scrape parser, API page iterator).
        Raw-row shape assertions live here.
        """
        raise NotImplementedError

    @abstractmethod
    def transform(self, context: PipelineContext) -> None:
        """Read raw rows; shape into cold_case.cases / victim / contact.

        All derivations happen here. Post-write canonical-row validation also
        happens here.
        """
        raise NotImplementedError

    def publish(self, context: PipelineContext) -> None:
        """Mark the dataset_version as published.

        Default impl is correct for every cold-case adapter.
        """
        from casesignal.etl.services.dataset_publishing import publish_dataset

        publish_dataset(context)

    def log_stage_start(self, context: PipelineContext, stage_name: str) -> None:
        if context.logger is not None:
            context.logger.info(
                "Starting stage '%s' for source '%s'.",
                stage_name,
                context.source_key,
            )

    def log_stage_end(self, context: PipelineContext, stage_name: str) -> None:
        if context.logger is not None:
            context.logger.info(
                "Completed stage '%s' for source '%s'.",
                stage_name,
                context.source_key,
            )

    def run_stage(
        self,
        context: PipelineContext,
        stage_name: str,
        stage_fn: Callable[[PipelineContext], Any],
    ) -> Any:
        """Run a pipeline stage with stage-record bookkeeping and logging."""
        stage_started_at = datetime.now(timezone.utc)
        row_count_before = context.total_row_count
        stage_record_id = record_stage_start(context, stage_name, stage_started_at)

        self.log_stage_start(context, stage_name)
        try:
            result = stage_fn(context)
        except Exception as exc:
            record_stage_finish(
                context=context,
                stage_record_id=stage_record_id,
                stage_name=stage_name,
                started_at=stage_started_at,
                completed_at=datetime.now(timezone.utc),
                stage_status="failed",
                rows_loaded=max(context.total_row_count - row_count_before, 0),
                notes=str(exc),
            )
            raise

        self.log_stage_end(context, stage_name)
        record_stage_finish(
            context=context,
            stage_record_id=stage_record_id,
            stage_name=stage_name,
            started_at=stage_started_at,
            completed_at=datetime.now(timezone.utc),
            stage_status="succeeded",
            rows_loaded=max(context.total_row_count - row_count_before, 0),
        )
        return result

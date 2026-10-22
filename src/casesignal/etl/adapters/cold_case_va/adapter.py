"""ColdCaseVAAdapter — SourceAdapter for the VA VSPCCD CSV extract."""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseVAAdapter(SourceAdapter):
    """Concrete source adapter for Virginia cold case CSV snapshots."""

    adapter_name = "cold_case_va"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Validate the CSV input exists and stash paths on context."""
        source = self.source_definition
        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        if source.input_type != "csv":
            raise ValueError(
                f"ColdCaseVAAdapter does not support input_type '{source.input_type}'"
                f" for source '{source.source_key}' (expected 'csv')."
            )

        input_path = source.input_path
        if not input_path.exists():
            raise FileNotFoundError(
                f"Input CSV does not exist for source '{source.source_key}': {input_path}"
            )
        if not input_path.is_file():
            raise ValueError(f"Expected a file, got: {input_path}")

        context.extracted_path = input_path.parent
        context.set_metadata("resolved_input_path", str(input_path))
        context.set_metadata("input_mode", "csv")

        context.logger.info(
            "Cold case VA input validated for source '%s' at %s",
            source.source_key,
            input_path,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_va.register import register_cold_case_source

        register_cold_case_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_va.raw_load import load_cold_case_raw

        load_cold_case_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_va.transform import transform_cold_case

        transform_cold_case(context)

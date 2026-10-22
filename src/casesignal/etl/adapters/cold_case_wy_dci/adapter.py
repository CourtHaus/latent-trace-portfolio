"""Wyoming DCI cold-case adapter (state #7).

CSV-only ingest. Mirrors cold_case_va shape — no scraping, no LLM.
transform.py lands in Task D (lazy-imported inside transform() so the
shell still imports cleanly until then).
"""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.adapters.cold_case_wy_dci.raw_load import load_cold_case_raw
from casesignal.etl.adapters.cold_case_wy_dci.register import register_cold_case_source
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseWyDciAdapter(SourceAdapter):
    """Concrete source adapter for the Wyoming DCI cold-case CSV extract."""

    adapter_name = "cold_case_wy_dci"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Validate the unified WY CSV exists and stash paths on context.

        Photo directory existence is checked at transform time (Task D).
        """
        source = self.source_definition
        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        if source.input_type != "csv":
            raise ValueError(
                f"ColdCaseWyDciAdapter does not support input_type '{source.input_type}'"
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
            "Cold case WY DCI input validated for source '%s' at %s",
            source.source_key,
            input_path,
        )

    def register_source(self, context: PipelineContext) -> None:
        register_cold_case_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        load_cold_case_raw(context)

    def transform(self, context: PipelineContext) -> None:
        # Lazy import — Task D creates transform.py. Until then this raises
        # ImportError at call time, which is fine because no end-to-end run
        # happens until Task D lands.
        from casesignal.etl.adapters.cold_case_wy_dci.transform import transform_wy

        transform_wy(context)

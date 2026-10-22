"""ColdCaseMDHowardAdapter — SourceAdapter for Howard County PD."""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseMDHowardAdapter(SourceAdapter):
    """Concrete source adapter for Howard County, MD PD cold cases."""

    adapter_name = "cold_case_md_howard"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch the single index page; parse sections; stash on context.

        Howard's site is one page (no detail-page link discovery), so we
        parse here and pass the parsed CaseSection list to load_raw via
        context metadata.
        """
        from casesignal.etl.adapters.cold_case_md_howard.scrape import (
            parse_cold_case_sections,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(f"Howard adapter requires input_type='url', got '{source.input_type}'")
        # SourceDefinition stores input_path as a Path; pathlib collapses
        # `https://` to `https:/` (a single slash). Normalize back so URLs
        # parse correctly downstream.
        index_url = str(source.input_path)
        if index_url.startswith(("http:/", "https:/")) and not index_url.startswith(
            ("http://", "https://")
        ):
            index_url = index_url.replace("http:/", "http://", 1).replace("https:/", "https://", 1)
        if not index_url.startswith(("http://", "https://")):
            raise ValueError(f"Howard input_path must be an absolute URL, got '{index_url}'")

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        response = polite.get(index_url)
        sections = parse_cold_case_sections(response.text, base_url=index_url)
        if len(sections) < 15:
            raise RuntimeError(
                f"Howard prepare_input: parsed {len(sections)} sections from {index_url};"
                f" expected >= 15. Page structure may have changed."
            )

        context.set_metadata("howard_sections", sections)
        context.set_metadata("howard_index_url", index_url)
        context.logger.info(
            "Howard prepare_input: parsed %d sections from %s",
            len(sections),
            index_url,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_howard.register import (
            register_howard_source,
        )

        register_howard_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        # The load_raw module is created in Task B3.
        from casesignal.etl.adapters.cold_case_md_howard.raw_load import (
            load_howard_raw,
        )

        load_howard_raw(context)

    def transform(self, context: PipelineContext) -> None:
        # The transform module is created in Task B4.
        from casesignal.etl.adapters.cold_case_md_howard.transform import (
            transform_howard,
        )

        transform_howard(context)

        # Close the polite_http client at end of transform — matches AA
        # pattern. publish() default impl doesn't need it.
        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

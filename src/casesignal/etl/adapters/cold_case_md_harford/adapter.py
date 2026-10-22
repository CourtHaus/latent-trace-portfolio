"""ColdCaseMDHarfordAdapter — SourceAdapter for Harford County Sheriff."""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseMDHarfordAdapter(SourceAdapter):
    """Concrete source adapter for Harford County, MD Sheriff cold cases."""

    adapter_name = "cold_case_md_harford"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch the single index page; parse sections; stash on context.

        Harford's site is one page (no detail-page link discovery), so we
        parse here and pass the parsed CaseSection list to load_raw via
        context metadata.
        """
        from casesignal.etl.adapters.cold_case_md_harford.scrape import (
            parse_cold_case_sections,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(
                f"Harford adapter requires input_type='url', got '{source.input_type}'"
            )
        # SourceDefinition stores input_path as a Path; pathlib collapses
        # `https://` to `https:/` (a single slash). Normalize back so URLs
        # parse correctly downstream.
        index_url = str(source.input_path)
        if index_url.startswith(("http:/", "https:/")) and not index_url.startswith(
            ("http://", "https://")
        ):
            index_url = index_url.replace("http:/", "http://", 1).replace("https:/", "https://", 1)
        if not index_url.startswith(("http://", "https://")):
            raise ValueError(f"Harford input_path must be an absolute URL, got '{index_url}'")

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        response = polite.get(index_url)
        sections = parse_cold_case_sections(response.text, base_url=index_url)
        if len(sections) < 15:
            raise RuntimeError(
                f"Harford prepare_input: parsed {len(sections)} sections from {index_url};"
                f" expected >= 15. Page structure may have changed."
            )

        context.set_metadata("harford_sections", sections)
        context.set_metadata("harford_index_url", index_url)
        context.logger.info(
            "Harford prepare_input: parsed %d sections from %s",
            len(sections),
            index_url,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_harford.register import (
            register_harford_source,
        )

        register_harford_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        # The load_raw module is created in Task C3.
        from casesignal.etl.adapters.cold_case_md_harford.raw_load import (
            load_harford_raw,
        )

        load_harford_raw(context)

    def transform(self, context: PipelineContext) -> None:
        # The transform module is created in Task C4.
        from casesignal.etl.adapters.cold_case_md_harford.transform import (
            transform_harford,
        )

        transform_harford(context)

        # Close the polite_http client at end of transform — matches AA
        # pattern. publish() default impl doesn't need it.
        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

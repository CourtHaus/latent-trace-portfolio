"""ColdCaseMDAnneArundelAdapter — SourceAdapter for Anne Arundel PD."""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseMDAnneArundelAdapter(SourceAdapter):
    """Concrete source adapter for Anne Arundel County, MD PD cold cases."""

    adapter_name = "cold_case_md_anne_arundel"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch the single index page; parse sections; stash on context.

        AA's site is one page (no detail-page link discovery), so we
        parse here and pass the parsed CaseSection list to load_raw via
        context metadata.
        """
        from casesignal.etl.adapters.cold_case_md_anne_arundel.scrape import (
            parse_cold_case_sections,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(f"AA adapter requires input_type='url', got '{source.input_type}'")
        # SourceDefinition stores input_path as a Path; pathlib collapses
        # `https://` to `https:/` (a single slash). Normalize back so URLs
        # parse correctly downstream.
        index_url = str(source.input_path)
        if index_url.startswith(("http:/", "https:/")) and not index_url.startswith(
            ("http://", "https://")
        ):
            index_url = index_url.replace("http:/", "http://", 1).replace("https:/", "https://", 1)
        if not index_url.startswith(("http://", "https://")):
            raise ValueError(f"AA input_path must be an absolute URL, got '{index_url}'")

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        response = polite.get(index_url)
        sections = parse_cold_case_sections(response.text, base_url=index_url)
        if len(sections) < 30:
            raise RuntimeError(
                f"AA prepare_input: parsed {len(sections)} sections from {index_url};"
                f" expected >= 30. Page structure may have changed."
            )

        context.set_metadata("aa_sections", sections)
        context.set_metadata("aa_index_url", index_url)
        context.logger.info(
            "AA prepare_input: parsed %d sections from %s",
            len(sections),
            index_url,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_anne_arundel.register import (
            register_aa_source,
        )

        register_aa_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        # The load_raw module is created in Task C3.
        from casesignal.etl.adapters.cold_case_md_anne_arundel.raw_load import (
            load_aa_raw,
        )

        load_aa_raw(context)

    def transform(self, context: PipelineContext) -> None:
        # The transform module is created in Task C4.
        from casesignal.etl.adapters.cold_case_md_anne_arundel.transform import (
            transform_aa,
        )

        transform_aa(context)

        # Close the polite_http client at end of transform — matches BCounty
        # pattern. publish() default impl doesn't need it.
        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

"""ColdCaseMDCharlesAdapter — SourceAdapter for Charles County Sheriff cold cases."""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseMDCharlesAdapter(SourceAdapter):
    """Concrete source adapter for Charles County, MD Sheriff cold cases."""

    adapter_name = "cold_case_md_charles"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch the index page; parse CaseRef list; stash on context.

        Charles's site is an index page with links to individual detail pages.
        We parse here to get a list[CaseRef] and pass it to load_raw via
        context metadata.
        """
        from casesignal.etl.adapters.cold_case_md_charles.scrape import (
            parse_index,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(
                f"Charles adapter requires input_type='url', got '{source.input_type}'"
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
            raise ValueError(f"Charles input_path must be an absolute URL, got '{index_url}'")

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        response = polite.get(index_url)
        refs = parse_index(response.text, base_url=index_url)
        if len(refs) < 3:
            raise RuntimeError(
                f"Charles prepare_input: parsed {len(refs)} refs from {index_url};"
                f" expected >= 3. Page structure may have changed."
            )

        context.set_metadata("charles_refs", refs)
        context.set_metadata("charles_index_url", index_url)
        context.logger.info(
            "Charles prepare_input: parsed %d refs from %s",
            len(refs),
            index_url,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_charles.register import (
            register_charles_source,
        )

        register_charles_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_charles.raw_load import (
            load_charles_raw,
        )

        load_charles_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_charles.transform import (
            transform_charles,
        )

        transform_charles(context)

        # Close the polite_http client at end of transform — matches Howard/AA pattern.
        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

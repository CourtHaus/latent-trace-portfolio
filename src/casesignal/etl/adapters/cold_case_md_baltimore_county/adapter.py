"""ColdCaseMDBaltimoreCountyAdapter — SourceAdapter for BCounty PD scrapes."""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseMDBaltimoreCountyAdapter(SourceAdapter):
    """Concrete source adapter for Baltimore County, MD PD unsolved homicides."""

    adapter_name = "cold_case_md_baltimore_county"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch the index page; parse + stash detail-page URLs.

        `source.input_path` is treated as the index URL string for this
        adapter (sources.yaml entry sets input_type='url'). Constructs a
        PoliteHTTPClient on context.metadata so subsequent stages (load_raw)
        share rate-limit + robots.txt cache state.
        """
        from casesignal.etl.adapters.cold_case_md_baltimore_county.scrape import (
            parse_index_links,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(
                f"BCounty adapter requires input_type='url', got '{source.input_type}'"
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
            raise ValueError(f"BCounty input_path must be an absolute URL, got '{index_url}'")

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        response = polite.get(index_url)
        detail_pairs = parse_index_links(response.text, base_url=index_url)
        if not detail_pairs:
            raise RuntimeError(
                f"BCounty prepare_input: no detail-page links found at {index_url};"
                f" page structure may have changed."
            )

        context.set_metadata("bcounty_detail_urls", detail_pairs)
        context.set_metadata("bcounty_index_url", index_url)
        context.logger.info(
            "BCounty prepare_input: discovered %d detail-page links from %s",
            len(detail_pairs),
            index_url,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_baltimore_county.register import (
            register_bcounty_source,
        )

        register_bcounty_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_baltimore_county.raw_load import (
            load_bcounty_raw,
        )

        load_bcounty_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_baltimore_county.transform import (
            transform_bcounty,
        )

        transform_bcounty(context)

        # Close the polite_http client at end of transform — it has a session
        # that should be released. publish() default impl doesn't need it.
        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

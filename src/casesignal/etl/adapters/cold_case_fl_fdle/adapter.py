"""ColdCaseFLFDLEAdapter — Florida FDLE statewide unsolved cases."""

from __future__ import annotations

import logging

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)


class ColdCaseFLFDLEAdapter(SourceAdapter):
    """Concrete source adapter for Florida FDLE unsolved cases."""

    adapter_name = "cold_case_fl_fdle"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_fl_fdle.scrape import (
            DEFAULT_CASE_TYPES,
            FDLEJSFScraper,
            detail_to_raw_dict,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        meta = self.source_definition.metadata or {}
        case_types = tuple(meta.get("case_types") or DEFAULT_CASE_TYPES)
        rows_per_page = int(meta.get("rows_per_page") or 50)
        max_photo_failure_ratio = float(meta.get("max_photo_failure_ratio") or 0.5)

        polite = PoliteHTTPClient()
        scraper = FDLEJSFScraper(polite)
        details = scraper.scrape_all(case_types=case_types, rows_per_page=rows_per_page)
        entries = [detail_to_raw_dict(detail) for detail in details]
        if not entries:
            raise RuntimeError("FL FDLE scrape returned zero entries; refusing to ingest.")

        context.set_metadata("polite_http", polite)
        context.set_metadata("fl_entries", entries)
        context.set_metadata("fl_live_count", len(entries))
        context.set_metadata("max_photo_failure_ratio", max_photo_failure_ratio)
        context.logger.info(
            "FL FDLE prepare_input: %d entries from case_types=%s",
            len(entries),
            ",".join(case_types),
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_fl_fdle.register import register_fl_source

        register_fl_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_fl_fdle.raw_load import load_fl_raw

        load_fl_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_fl_fdle.transform import transform_fl

        try:
            transform_fl(context)
        finally:
            polite = context.get_metadata("polite_http")
            if polite is not None and hasattr(polite, "close"):
                try:
                    polite.close()
                except Exception:
                    pass

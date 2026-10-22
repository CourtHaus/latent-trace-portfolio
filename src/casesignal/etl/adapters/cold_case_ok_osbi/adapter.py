"""ColdCaseOKOSBIAdapter — Oklahoma OSBI cold cases."""

from __future__ import annotations

import logging
from typing import Any

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)

_OK_RATE_LIMIT_SECONDS = 2.0  # robots is allow-all; default polite pace
_MIN_EXPECTED_CASES = 250  # ~400 live; a big drop means the site changed
_MIN_EXPECTED_RANGE_PAGES = 10


def entry_from_case(case: Any) -> dict[str, Any]:
    """Shape one OkCase into the raw-entry dict."""
    from casesignal.etl.adapters.cold_case_ok_osbi.transform import (
        map_case_type,
        normalize_ok_date,
    )

    return {
        "name": case.name,
        "case_name": case.name,
        "case_type": map_case_type(case.case_type_label),
        "date_text": case.date_text,
        "incident_date_iso": normalize_ok_date(case.date_text),
        "narrative": case.narrative,
        "contact_text": case.contact_text,
        "photo": (
            {
                "source_url": case.photo.source_url,
                "alt": case.photo.alt,
                "filename_hint": case.photo.filename_hint,
            }
            if case.photo is not None
            else None
        ),
    }


class ColdCaseOKOSBIAdapter(SourceAdapter):
    """Concrete source adapter for Oklahoma OSBI cold cases."""

    adapter_name = "cold_case_ok_osbi"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ok_osbi.scrape import (
            INDEX_URL,
            parse_range_page,
            parse_range_page_links,
        )
        from casesignal.etl.adapters.cold_case_ok_osbi.transform import (
            assign_source_case_ids,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        meta = self.source_definition.metadata or {}
        raw_rate_limit = meta.get("rate_limit_seconds")
        rate_limit = float(raw_rate_limit if raw_rate_limit is not None else _OK_RATE_LIMIT_SECONDS)
        raw_max_photo_failure_ratio = meta.get("max_photo_failure_ratio")
        max_photo_failure_ratio = float(
            raw_max_photo_failure_ratio if raw_max_photo_failure_ratio is not None else 0.5
        )
        index_url = str(meta.get("source_url") or INDEX_URL)

        polite = PoliteHTTPClient(rate_limit_seconds=rate_limit)
        index_html = polite.get(index_url).text
        range_urls = parse_range_page_links(index_html, index_url)
        context.logger.info("OK OSBI prepare_input: %d range pages", len(range_urls))
        if len(range_urls) < _MIN_EXPECTED_RANGE_PAGES:
            raise RuntimeError(
                f"OK OSBI index returned only {len(range_urls)} range pages "
                f"(< {_MIN_EXPECTED_RANGE_PAGES}); source layout may have changed."
            )

        entries: list[dict[str, Any]] = []
        for url in range_urls:
            page_html = polite.get(url).text
            for case in parse_range_page(page_html, base_url=url, logger=context.logger):
                entry = entry_from_case(case)
                entry["source_range_url"] = url
                entries.append(entry)

        if len(entries) < _MIN_EXPECTED_CASES:
            raise RuntimeError(
                f"OK OSBI scrape returned only {len(entries)} cases "
                f"(< {_MIN_EXPECTED_CASES}); refusing to ingest."
            )
        assign_source_case_ids(entries)

        unmapped = sum(1 for e in entries if e.get("case_type") == "cold_case")
        no_contact = sum(1 for e in entries if e.get("contact_text") is None)
        if entries:
            if unmapped / len(entries) > 0.1:
                context.logger.warning(
                    "OK OSBI: %d/%d entries (%.1f%%) have an unmapped case_type "
                    "('cold_case'); a parser variant may be silently dropping the "
                    "type/date line.",
                    unmapped,
                    len(entries),
                    100 * unmapped / len(entries),
                )
            if no_contact / len(entries) > 0.1:
                context.logger.warning(
                    "OK OSBI: %d/%d entries (%.1f%%) have no contact_text; a "
                    "parser variant may be silently dropping the contact line.",
                    no_contact,
                    len(entries),
                    100 * no_contact / len(entries),
                )

        context.set_metadata("polite_http", polite)
        context.set_metadata("ok_entries", entries)
        context.set_metadata("max_photo_failure_ratio", max_photo_failure_ratio)

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ok_osbi.register import register_ok_source

        register_ok_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ok_osbi.raw_load import load_ok_raw

        load_ok_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ok_osbi.transform import transform_ok

        try:
            transform_ok(context)
        finally:
            polite = context.get_metadata("polite_http")
            if polite is not None and hasattr(polite, "close"):
                try:
                    polite.close()
                except Exception:
                    pass

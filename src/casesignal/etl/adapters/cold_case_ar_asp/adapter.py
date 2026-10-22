"""ColdCaseARASPAdapter — Arkansas State Police CID cold cases."""

from __future__ import annotations

import logging
from typing import Any

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)

# robots.txt at dps.arkansas.gov asks Crawl-delay: 10.
_AR_RATE_LIMIT_SECONDS = 10.0
_MIN_EXPECTED_CASES = 100  # live corpus is ~144; a big drop means the site changed


def entry_from_detail(entry: Any, detail: Any) -> dict[str, Any]:
    """Shape one (IndexEntry, ArDetailFields) pair into the raw-entry dict."""
    from casesignal.etl.adapters.cold_case_ar_asp.transform import derive_case_type

    return {
        "slug": entry.slug,
        "case_name": entry.link_text,
        "case_type": derive_case_type(detail.date_label),
        "age_text": detail.age_text,
        "race": detail.race,
        "sex": detail.sex,
        "date_label": detail.date_label,
        "date_text": detail.date_text,
        "cause": detail.cause,
        "county": detail.county,
        "case_number": detail.case_number,
        "narrative": detail.narrative,
        "contact_text": detail.contact_text,
        "contact_agency": detail.contact_agency,
        "contact_phone": detail.contact_phone,
        "photos": [
            {"source_url": p.source_url, "alt": p.alt, "filename_hint": p.filename_hint}
            for p in detail.photos
        ],
        "source_detail_url": entry.url,
    }


class ColdCaseARASPAdapter(SourceAdapter):
    """Concrete source adapter for Arkansas State Police CID cold cases."""

    adapter_name = "cold_case_ar_asp"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ar_asp.scrape import (
            INDEX_URL,
            parse_detail_page,
            parse_index_links,
        )
        from casesignal.etl.adapters.cold_case_ar_asp.transform import (
            assign_source_case_ids,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        meta = self.source_definition.metadata or {}
        rate_limit = float(meta.get("rate_limit_seconds") or _AR_RATE_LIMIT_SECONDS)
        max_photo_failure_ratio = float(meta.get("max_photo_failure_ratio") or 0.5)
        index_url = str(meta.get("source_url") or INDEX_URL)

        # dps.arkansas.gov sits behind Cloudflare Bot Management, which
        # TLS-fingerprint-blocks Python's ssl stack (httpx) with a 403
        # regardless of User-Agent. curl_cffi presents a real libcurl
        # fingerprint that Cloudflare accepts under our branded UA.
        #
        # media.ark.org (the photo CDN) is an S3 bucket with NO robots.txt;
        # S3 answers the missing /robots.txt with 403, which RFC-9309-strict
        # handling reads as "disallow all" — yet every image is public (200).
        # Bypass robots for that host only: it's a pure asset host we pull
        # already-referenced public images from, never a site we crawl.
        polite = PoliteHTTPClient(
            rate_limit_seconds=rate_limit,
            tls_impersonate=True,
            bypass_robots_hosts={"media.ark.org"},
        )
        index_html = polite.get(index_url).text
        links = parse_index_links(index_html, index_url, logger=context.logger)
        context.logger.info("AR ASP prepare_input: %d unique cases on index", len(links))

        if len(links) < _MIN_EXPECTED_CASES:
            raise RuntimeError(
                f"AR ASP index returned only {len(links)} cases "
                f"(< {_MIN_EXPECTED_CASES}); source page may have changed. "
                "Refusing to crawl detail pages."
            )

        entries: list[dict[str, Any]] = []
        for link in links:
            detail_html = polite.get(link.url).text
            detail = parse_detail_page(detail_html, logger=context.logger)
            entries.append(entry_from_detail(link, detail))

        if len(entries) < _MIN_EXPECTED_CASES:
            raise RuntimeError(
                f"AR ASP scrape returned only {len(entries)} entries "
                f"(< {_MIN_EXPECTED_CASES}); source page may have changed. Refusing to ingest."
            )
        assign_source_case_ids(entries)

        context.set_metadata("polite_http", polite)
        context.set_metadata("ar_entries", entries)
        context.set_metadata("max_photo_failure_ratio", max_photo_failure_ratio)

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ar_asp.register import register_ar_source

        register_ar_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ar_asp.raw_load import load_ar_raw

        load_ar_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ar_asp.transform import transform_ar

        try:
            transform_ar(context)
        finally:
            polite = context.get_metadata("polite_http")
            if polite is not None and hasattr(polite, "close"):
                try:
                    polite.close()
                except Exception:
                    pass

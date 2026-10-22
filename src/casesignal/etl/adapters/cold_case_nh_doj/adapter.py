"""ColdCaseNhDojAdapter — SourceAdapter for NH DOJ Cold Case Unit."""

from __future__ import annotations

import logging

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)

# Canonical API endpoint. `SourceDefinition.input_path` is a `Path` which
# mangles `https://` → `https:/`, so URL-typed sources read from a string
# constant here (matches the OH AG pattern of reading from `meta.list_url`).
_API_URL = (
    "https://www.doj.nh.gov/content/api/documents"
    "?q=%40field_document_subcategory%7C%3D%7C6816"
    "&textsearch=&sort=title%7Casc%7CALLOW_NULLS"
    "&iterate_nodes=true&filter_mode=inclusive"
    "&type=document&size=200&page=1"
)


class ColdCaseNhDojAdapter(SourceAdapter):
    """Concrete source adapter for the NH DOJ Cold Case Unit victim list."""

    adapter_name = "cold_case_nh_doj"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Verify the JSON API responds + parse the in-scope row list.

        Akamai bot filter requires Firefox-class UA + bypass of (403'd)
        robots.txt for www.doj.nh.gov. Both via CASESIGNAL_* env knobs.
        """
        from casesignal.etl.adapters.cold_case_nh_doj.scrape_index import (
            parse_index_response,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        meta = source.metadata or {}
        baseline_count = int(meta.get("baseline_count") or 0)
        if baseline_count <= 0:
            raise RuntimeError("NH adapter requires source.metadata.baseline_count > 0")

        from casesignal.etl.adapters.cold_case_oh_ag.scrape_search import drift_check

        api_url = (source.metadata or {}).get("api_url", _API_URL)

        polite = PoliteHTTPClient()
        resp = polite.get(api_url)
        rows = parse_index_response(resp.text)
        live_count = len(rows)

        # Symmetric drift gate (shared with OH): pass <5%, warn 5-20%, abort >=20%.
        # Catches unexpected growth (e.g., scope expansion) as well as shrink.
        verdict = drift_check(baseline=baseline_count, live=live_count)
        if verdict == "abort":
            raise RuntimeError(
                f"NH live count {live_count} diverged >=20% from baseline "
                f"{baseline_count}; refusing to ingest until reconciled "
                "(re-run or update baseline_count)."
            )
        if verdict == "warn":
            context.logger.warning(
                "NH drift: live=%d vs baseline=%d (delta=%.1f%%); proceeding",
                live_count,
                baseline_count,
                abs(live_count - baseline_count) / baseline_count * 100.0,
            )

        context.set_metadata("polite_http", polite)
        context.set_metadata("nh_index_rows", rows)
        context.set_metadata("nh_total_live", live_count)
        context.set_metadata("nh_baseline_count", baseline_count)
        context.set_metadata("nh_drift_verdict", verdict)
        context.logger.info(
            "NH prepare_input: %d in-scope rows from API (baseline=%d, drift=%s)",
            live_count,
            baseline_count,
            verdict,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_nh_doj.register import (
            register_nh_source,
        )

        register_nh_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_nh_doj.raw_load import load_nh_raw

        load_nh_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_nh_doj.transform import transform_nh

        transform_nh(context)

        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

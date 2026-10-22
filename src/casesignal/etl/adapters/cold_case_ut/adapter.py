"""ColdCaseUTAdapter — SourceAdapter for Utah BCI cold-case database."""

from __future__ import annotations

import logging

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.adapters.cold_case_ut.scrape_sitemap import (
    SitemapEntry,
    drift_check,
    parse_sitemap,
)
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)


class ColdCaseUTAdapter(SourceAdapter):
    """Concrete source adapter for Utah BCI cold cases."""

    adapter_name = "cold_case_ut"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch sitemap → parse → drift-check → stash on context."""
        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(f"UT adapter requires input_type='url', got '{source.input_type}'")

        # PipelineContext converts source_path via Path(), which collapses
        # the double-slash in URLs ("https://x" → "https:/x"). Restore.
        sitemap_url = str(source.input_path).rstrip("/")
        if sitemap_url.startswith(("http:/", "https:/")) and not sitemap_url.startswith(
            ("http://", "https://")
        ):
            sitemap_url = sitemap_url.replace("http:/", "http://", 1).replace(
                "https:/", "https://", 1
            )
        if not sitemap_url.startswith(("http://", "https://")):
            raise ValueError(f"UT input_path must be an absolute URL, got '{sitemap_url}'")

        meta = source.metadata or {}
        baseline_count = int(meta.get("baseline_count") or 0)
        if baseline_count <= 0:
            raise RuntimeError("UT adapter requires source.metadata.baseline_count > 0")

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        # Single GET — no pagination at this scale (recon-verified: ~497 entries)
        resp = polite.get(sitemap_url)
        entries: list[SitemapEntry] = parse_sitemap(resp.text)
        if not entries:
            raise RuntimeError("UT sitemap parse returned 0 entries; refusing to proceed.")

        # Drift check against all-types count
        verdict = drift_check(baseline=baseline_count, live=len(entries))
        if verdict == "abort":
            raise RuntimeError(
                f"UT live sitemap count {len(entries)} diverged > 20% from baseline {baseline_count}; "
                "refusing to ingest until reconciled."
            )
        if verdict == "warn":
            context.logger.warning(
                "UT drift: live=%d vs baseline=%d (Δ=%.1f%%); proceeding "
                "(note: all-types signal, less precise than typed)",
                len(entries),
                baseline_count,
                abs(len(entries) - baseline_count) / baseline_count * 100.0,
            )

        context.set_metadata("ut_sitemap_entries", entries)
        context.set_metadata("ut_baseline_count", baseline_count)
        context.set_metadata("ut_drift_verdict", verdict)
        context.logger.info(
            "UT prepare_input: %d sitemap entries (live=%d, baseline=%d, drift=%s)",
            len(entries),
            len(entries),
            baseline_count,
            verdict,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ut.register import register_ut_source

        register_ut_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ut.raw_load import load_ut_raw

        load_ut_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_ut.transform import transform_ut

        transform_ut(context)

        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

"""ColdCaseOHAdapter — SourceAdapter for Ohio AG statewide unsolved homicides."""

from __future__ import annotations

import logging

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)


class ColdCaseOHAdapter(SourceAdapter):
    """Concrete source adapter for Ohio AG statewide unsolved homicides."""

    adapter_name = "cold_case_oh_ag"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Paginate the OH AG cold-case listing + drift-check vs baseline.

        OH AG's `Cold-Case` landing page paginates via a plain `?page=N` GET
        query parameter. We walk pages 1..N until a page returns zero new
        rows, deduping by detail URL. The pager block on each page also
        reports `(of NNNN total)` which we capture for completeness, but
        the authoritative live count is the deduped row total.
        """
        from casesignal.etl.adapters.cold_case_oh_ag.scrape_search import (
            SearchResultRow,
            drift_check,
            paginate_all,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        meta = source.metadata or {}
        baseline_count = int(meta.get("baseline_count") or 0)
        if baseline_count <= 0:
            raise RuntimeError("OH adapter requires source.metadata.baseline_count > 0")

        base_list_url = meta.get(
            "list_url",
            "https://www.ohioattorneygeneral.gov/Law-Enforcement/Local-Law-Enforcement/Cold-Case",
        )

        polite = PoliteHTTPClient()
        if hasattr(polite, "_client"):
            polite._client.follow_redirects = True

        rows: list[SearchResultRow] = list(paginate_all(polite, base_list_url=base_list_url))
        live_count = len(rows)

        verdict = drift_check(baseline=baseline_count, live=live_count)
        if verdict == "abort":
            raise RuntimeError(
                f"OH listing count {live_count} diverged > 20% from baseline {baseline_count}; "
                "refusing to ingest until reconciled (re-run or update baseline_count)."
            )
        if verdict == "warn":
            context.logger.warning(
                "OH drift: live=%d vs baseline=%d (delta=%.1f%%); proceeding",
                live_count,
                baseline_count,
                abs(live_count - baseline_count) / baseline_count * 100.0,
            )

        context.set_metadata("polite_http", polite)
        context.set_metadata("oh_search_rows", rows)
        context.set_metadata("oh_total_live", live_count)
        context.set_metadata("oh_baseline_count", baseline_count)
        context.set_metadata("oh_drift_verdict", verdict)
        context.logger.info(
            "OH prepare_input: %d unique rows from paginated GET (baseline=%d, drift=%s)",
            live_count,
            baseline_count,
            verdict,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_oh_ag.register import register_oh_source

        register_oh_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_oh_ag.raw_load import load_oh_raw

        load_oh_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_oh_ag.transform import transform_oh

        transform_oh(context)

        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

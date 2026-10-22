"""ColdCaseCOAdapter — SourceAdapter for Colorado CBI cold-case database."""

from __future__ import annotations

import logging

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)


class ColdCaseCOAdapter(SourceAdapter):
    """Concrete source adapter for Colorado CBI cold cases."""

    adapter_name = "cold_case_co"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Read browser-scraped case index from JSON manifest + drift check vs baseline.

        Background: CBI's apps.colorado.gov server-side pagination ignores the
        `page` POST param when the request comes from non-browser clients
        (curl, httpx, even headless Playwright). The "of NNNN total" count
        updates but the rendered case list is the same 10 cases on every
        page. Verified across 8+ different request shapes.

        Workaround: a one-time Violentmonkey userscript (tools/co_userscript.user.js)
        runs in a real browser session and scrapes the full paginated index,
        exporting a JSON file of {id, name} objects. This stage reads that
        file. Detail-page fetches in load_raw work fine via polite_http.
        """
        import json
        from pathlib import Path

        from casesignal.etl.adapters.cold_case_co.scrape_search import (
            SearchResultRow,
            drift_check,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        meta = source.metadata or {}
        baseline_count = int(meta.get("baseline_count") or 0)
        if baseline_count <= 0:
            raise RuntimeError("CO adapter requires source.metadata.baseline_count > 0")

        manifest_path_str = meta.get("search_index_json")
        if not manifest_path_str:
            raise RuntimeError(
                "CO adapter requires source.metadata.search_index_json — path to the "
                "JSON file exported by tools/co_userscript.user.js. See spec for details."
            )
        manifest_path = Path(manifest_path_str)
        if not manifest_path.is_absolute():
            manifest_path = Path.cwd() / manifest_path
        if not manifest_path.exists():
            raise RuntimeError(
                f"CO manifest file not found at {manifest_path}. Run the Violentmonkey "
                "userscript (tools/co_userscript.user.js) against apps.colorado.gov, "
                "then save the exported JSON to this path."
            )

        with manifest_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise RuntimeError(
                f"CO manifest at {manifest_path} must be a JSON array, got {type(raw).__name__}"
            )

        rows: list[SearchResultRow] = []
        seen: set[int] = set()
        base_url = "https://apps.colorado.gov/apps/coldcase/"
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict) or "id" not in entry or "name" not in entry:
                raise RuntimeError(
                    f"CO manifest entry {i} malformed: expected {{id: int, name: str}}, got {entry!r}"
                )
            detail_id = int(entry["id"])
            if detail_id in seen:
                continue
            seen.add(detail_id)
            rows.append(
                SearchResultRow(
                    name=str(entry["name"]).strip(),
                    detail_id=detail_id,
                    detail_url=f"{base_url}casedetail.html?id={detail_id}",
                )
            )

        live_count = len(rows)

        # Drift check (same thresholds as before)
        verdict = drift_check(baseline=baseline_count, live=live_count)
        if verdict == "abort":
            raise RuntimeError(
                f"CO manifest count {live_count} diverged > 20% from baseline {baseline_count}; "
                "refusing to ingest until reconciled (re-run userscript or update baseline_count)."
            )
        if verdict == "warn":
            context.logger.warning(
                "CO drift: manifest=%d vs baseline=%d (Δ=%.1f%%); proceeding",
                live_count,
                baseline_count,
                abs(live_count - baseline_count) / baseline_count * 100.0,
            )

        # PoliteHTTPClient still needed for detail-page + photo fetches in load_raw
        polite = PoliteHTTPClient()
        if hasattr(polite, "_client"):
            polite._client.follow_redirects = True
        context.set_metadata("polite_http", polite)

        context.set_metadata("co_search_rows", rows)
        context.set_metadata("co_total_live", live_count)
        context.set_metadata("co_baseline_count", baseline_count)
        context.set_metadata("co_drift_verdict", verdict)
        context.logger.info(
            "CO prepare_input: %d unique rows from manifest %s (baseline=%d, drift=%s)",
            len(rows),
            manifest_path,
            baseline_count,
            verdict,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_co.register import register_co_source

        register_co_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_co.raw_load import load_co_raw

        load_co_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_co.transform import transform_co

        transform_co(context)

        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

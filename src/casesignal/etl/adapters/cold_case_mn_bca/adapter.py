"""ColdCaseMnBcaAdapter — SourceAdapter for the Minnesota BCA Unsolved
Cases Database (homicides only, state #9).

The case list sits behind an Imperva WAF and is harvested out-of-band via
a browser console fetch (see the design doc's "Harvest contract"). This
adapter's input is that harvested JSON file (`input_type: file`). Per-case
SOC PDFs and victim photos are static assets that pass the WAF cookieless,
so load_raw fetches them programmatically via PoliteHTTPClient.
"""

from __future__ import annotations

import logging

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)


class ColdCaseMnBcaAdapter(SourceAdapter):
    """Concrete source adapter for the Minnesota BCA unsolved-homicide list."""

    adapter_name = "cold_case_mn_bca"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Validate the harvest file, parse it, drift-check vs baseline."""
        from casesignal.etl.adapters.cold_case_mn_bca.read_harvest import parse_harvest
        from casesignal.etl.adapters.cold_case_oh_ag.scrape_search import drift_check

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "file":
            raise ValueError(
                f"ColdCaseMnBcaAdapter requires input_type='file', got '{source.input_type}'"
            )
        input_path = source.input_path
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(
                f"MN BCA harvest file missing for source '{source.source_key}': {input_path}"
            )

        meta = source.metadata or {}
        baseline_count = int(meta.get("baseline_count") or 0)
        if baseline_count <= 0:
            raise RuntimeError("MN adapter requires source.metadata.baseline_count > 0")

        records = parse_harvest(input_path)
        live_count = len(records)

        verdict = drift_check(baseline=baseline_count, live=live_count)
        if verdict == "abort":
            raise RuntimeError(
                f"MN harvest count {live_count} diverged >=20% from baseline "
                f"{baseline_count}; refusing to ingest until reconciled "
                "(re-harvest or update baseline_count)."
            )
        if verdict == "warn":
            context.logger.warning(
                "MN drift: live=%d vs baseline=%d (delta=%.1f%%); proceeding",
                live_count,
                baseline_count,
                abs(live_count - baseline_count) / baseline_count * 100.0,
            )

        context.set_metadata("polite_http", PoliteHTTPClient())
        context.set_metadata("mn_harvest_records", records)
        context.set_metadata("mn_live_count", live_count)
        context.set_metadata("mn_baseline_count", baseline_count)
        context.set_metadata("mn_drift_verdict", verdict)
        context.logger.info(
            "MN prepare_input: %d homicide records from harvest (baseline=%d, drift=%s)",
            live_count,
            baseline_count,
            verdict,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_mn_bca.register import register_mn_source

        register_mn_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_mn_bca.raw_load import load_mn_raw

        load_mn_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_mn_bca.transform import transform_mn

        transform_mn(context)

        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:  # noqa: BLE001
                pass

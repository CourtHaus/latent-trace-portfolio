"""ColdCaseDCMPDCAdapter — SourceAdapter for DC Metropolitan Police
Department unsolved homicides.

Multi-layer scrape:
  1. prepare_input: hub page → list of (year_set, year_page_url) tuples,
     filtered to in-scope years per source.metadata.year_range.
  2. register_source: standard get-or-create source_system + dataset_version.
  3. load_raw: per year_page → fetch + parse → per case → fetch + parse
     detail + PDF → insert raw row.
  4. transform: read raw → write canonical model + Tier-1-only extraction
     job + multi-detective contacts + gender from honorific.
  5. publish: default ABC.
"""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseDCMPDCAdapter(SourceAdapter):
    """Concrete source adapter for Washington D.C. MPDC cold cases."""

    adapter_name = "cold_case_dc_mpdc"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch the hub; parse year-pages; filter to in-scope years."""
        from casesignal.etl.adapters.cold_case_dc_mpdc.scrape_index import (
            parse_year_index,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(
                f"DC MPDC adapter requires input_type='url', got '{source.input_type}'"
            )
        hub_url = str(source.input_path)
        if hub_url.startswith(("http:/", "https:/")) and not hub_url.startswith(
            ("http://", "https://")
        ):
            hub_url = hub_url.replace("http:/", "http://", 1).replace("https:/", "https://", 1)
        if not hub_url.startswith(("http://", "https://")):
            raise ValueError(f"DC MPDC input_path must be an absolute URL, got '{hub_url}'")

        # Read in-scope year_range from source metadata
        meta = source.metadata or {}
        year_range = meta.get("year_range") or []
        in_scope = set(year_range)
        if not in_scope:
            raise RuntimeError(
                "DC MPDC adapter requires source.metadata.year_range to be set "
                "(e.g., [2020] for Phase 1.8a)."
            )

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        # Fetch + parse the hub
        response = polite.get(hub_url)
        all_pages = parse_year_index(response.text, base_url=hub_url)

        # Filter to year-pages that contain at least one in-scope year
        scoped: list[tuple[frozenset[int], str]] = [
            (years, url) for (years, url) in all_pages if years & in_scope
        ]
        if not scoped:
            raise RuntimeError(
                f"DC MPDC prepare_input: no year-pages match in-scope years "
                f"{sorted(in_scope)}; hub had {len(all_pages)} year-pages total."
            )

        context.set_metadata("dc_year_pages", scoped)
        context.set_metadata("dc_in_scope_years", in_scope)
        context.set_metadata("dc_hub_url", hub_url)
        context.logger.info(
            "DC MPDC prepare_input: %d year-pages match in-scope years %s",
            len(scoped),
            sorted(in_scope),
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_dc_mpdc.register import (
            register_dc_mpdc_source,
        )

        register_dc_mpdc_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_dc_mpdc.raw_load import (
            load_dc_mpdc_raw,
        )

        load_dc_mpdc_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_dc_mpdc.transform import (
            transform_dc_mpdc,
        )

        transform_dc_mpdc(context)

        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass

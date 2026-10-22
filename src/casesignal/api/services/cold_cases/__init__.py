"""Cold-case service layer — split by surface.

Pre-split (PR #87), this was a single 821-line `cold_cases.py` module. Routes
imported a flat list of 7 names from it. The split moves each route's service
into its own submodule; this `__init__.py` re-exports the same 7 names so
`from casesignal.api.services.cold_cases import ...` keeps working for callers.

Submodules:
- bbox: parse_bbox + map row-limit constants
- filters: gender/race normalization + SortOrder SQL clauses (shared by list+map)
- list_service: list_cold_cases
- map_service: query_cold_cases_for_map
- detail_service: get_cold_case_by_id (+ private _build_extraction_block)
- filter_options_service: get_filter_options (orchestrator over 10 _query_* helpers)
- sources_summary_service: get_sources_summary (per-source aggregates for methodology)
"""

from __future__ import annotations

from casesignal.api.services.cold_cases.bbox import (
    CLUSTER_ZOOM_THRESHOLD,
    DEFAULT_MAP_LIMIT,
    MAX_MAP_LIMIT,
    parse_bbox,
)
from casesignal.api.services.cold_cases.coverage_histogram_service import get_coverage_histogram
from casesignal.api.services.cold_cases.detail_service import get_cold_case_by_id
from casesignal.api.services.cold_cases.facet_counts_service import get_facet_counts
from casesignal.api.services.cold_cases.filter_options_service import get_filter_options
from casesignal.api.services.cold_cases.list_service import list_cold_cases
from casesignal.api.services.cold_cases.map_service import (
    aggregate_cold_cases_for_map,
    query_cold_cases_for_map,
)
from casesignal.api.services.cold_cases.sources_summary_service import get_sources_summary
from casesignal.api.services.cold_cases.year_histogram_service import get_year_histogram

__all__ = [
    "CLUSTER_ZOOM_THRESHOLD",
    "DEFAULT_MAP_LIMIT",
    "MAX_MAP_LIMIT",
    "aggregate_cold_cases_for_map",
    "get_cold_case_by_id",
    "get_coverage_histogram",
    "get_facet_counts",
    "get_filter_options",
    "get_sources_summary",
    "get_year_histogram",
    "list_cold_cases",
    "parse_bbox",
    "query_cold_cases_for_map",
]

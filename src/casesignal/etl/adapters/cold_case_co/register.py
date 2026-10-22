"""Source registration for the CO CBI adapter.

source_hash = SHA256 of canonical sorted "<detail_id>|<name>" lines from the
live search result set. Stable across re-runs only when the live set is
unchanged — when cases solve/appear, the hash changes and a new
dataset_version is created. Shared registration lives in
etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib

from casesignal.etl.adapters.cold_case_co.scrape_search import SearchResultRow
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = "https://apps.colorado.gov/apps/coldcase/search.html"


def register_co_source(context: PipelineContext) -> None:
    rows: list[SearchResultRow] = context.get_metadata("co_search_rows") or []
    if not rows:
        raise RuntimeError("co_search_rows missing; prepare_input must run first.")
    register_cold_case_source(
        context,
        source_hash=canonical_rows_hash(rows),
        source_file_name=_SOURCE_URL,
        log_label="CO",
    )


def canonical_rows_hash(rows: list[SearchResultRow]) -> str:
    lines = sorted(f"{r.detail_id}|{r.name}" for r in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

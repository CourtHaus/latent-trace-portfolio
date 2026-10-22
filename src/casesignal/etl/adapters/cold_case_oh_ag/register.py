"""Source registration for the OH AG adapter.

source_hash = SHA256 of canonical sorted detail URLs from the live search
result set. Stable across re-runs only when the live set is unchanged — when
cases solve/appear, the hash changes and a new dataset_version is created.
Shared registration lives in etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib

from casesignal.etl.adapters.cold_case_oh_ag.scrape_search import SearchResultRow
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = (
    "https://www.ohioattorneygeneral.gov/Law-Enforcement/"
    "Bureau-of-Criminal-Investigation/Unsolved-Homicides"
)


def register_oh_source(context: PipelineContext) -> None:
    rows: list[SearchResultRow] = context.get_metadata("oh_search_rows") or []
    if not rows:
        raise RuntimeError("oh_search_rows missing; prepare_input must run first.")
    register_cold_case_source(
        context,
        source_hash=canonical_rows_hash(rows),
        source_file_name=_SOURCE_URL,
        log_label="OH",
    )


def canonical_rows_hash(rows: list[SearchResultRow]) -> str:
    lines = sorted(r.detail_url for r in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

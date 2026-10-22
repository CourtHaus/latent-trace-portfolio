"""Source registration for the NH DOJ Cold Case Unit adapter.

source_hash = SHA256 over the canonical sorted detail-URL list from the live
JSON API response. Stable across re-runs only when the live set is unchanged.
Shared registration lives in etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib
import json

from casesignal.etl.adapters.cold_case_nh_doj.scrape_index import IndexRecord
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = "https://www.doj.nh.gov/bureaus/new-hampshire-cold-case-unit/victim-list"


def register_nh_source(context: PipelineContext) -> None:
    rows: list[IndexRecord] = context.get_metadata("nh_index_rows") or []
    if not rows:
        raise RuntimeError("nh_index_rows missing; prepare_input must run first.")
    register_cold_case_source(
        context,
        source_hash=canonical_rows_hash(rows),
        source_file_name=_SOURCE_URL,
        log_label="NH",
    )


def canonical_rows_hash(rows: list[IndexRecord]) -> str:
    """Stable SHA256 over the sorted list of detail URLs."""
    payload = json.dumps(sorted(r.detail_url for r in rows), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

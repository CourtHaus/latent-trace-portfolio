"""Source registration for the Baltimore County, MD adapter.

source_hash is computed from the discovered detail-page URL list (scraped at
runtime, not a local file). Shared registration lives in
etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = "https://www.baltimorecountymd.gov/departments/police/unsolved/homicides"


def register_bcounty_source(context: PipelineContext) -> None:
    detail_urls = context.get_metadata("bcounty_detail_urls")
    if not detail_urls:
        raise RuntimeError(
            "bcounty_detail_urls missing from context metadata; prepare_input must run first."
        )
    register_cold_case_source(
        context,
        source_hash=canonical_url_list_hash(detail_urls),
        source_file_name=_SOURCE_URL,
        log_label="BCounty",
    )


def canonical_url_list_hash(urls: list[tuple[str, str]]) -> str:
    """SHA256 hash of the canonical URL list — stable identifier for the snapshot.

    `urls` is [(detail_url, source_case_id), ...]. We sort by source_case_id
    to make the hash insensitive to discovery order.
    """
    canonical = "\n".join(sorted(slug for _, slug in urls))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

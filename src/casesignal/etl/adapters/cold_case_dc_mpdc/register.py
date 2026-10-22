"""Source registration for DC MPDC adapter.

source_hash = SHA256 of canonical sorted (year_page_url, sorted_years) pairs.
Stable across re-scrapes when the hub's year-page list and in-scope range are
unchanged. Shared registration lives in etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = "https://mpdc.dc.gov/page/unsolved-homicides"


def register_dc_mpdc_source(context: PipelineContext) -> None:
    year_pages = context.get_metadata("dc_year_pages") or []
    if not year_pages:
        raise RuntimeError(
            "dc_year_pages missing from context metadata; prepare_input must run first."
        )
    register_cold_case_source(
        context,
        source_hash=canonical_year_pages_hash(year_pages),
        source_file_name=_SOURCE_URL,
        log_label="DC MPDC",
    )


def canonical_year_pages_hash(
    year_pages: list[tuple[frozenset[int], str]],
) -> str:
    """SHA256 of sorted '<url>|<sorted_years_csv>' lines."""
    lines = sorted(f"{url}|{','.join(str(y) for y in sorted(years))}" for years, url in year_pages)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

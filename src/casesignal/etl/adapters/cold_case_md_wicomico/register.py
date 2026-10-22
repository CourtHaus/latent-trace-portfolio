"""Source registration for Wicomico County, MD adapter.

source_hash = canonical sorted (source_case_id, case_name) pairs from the parsed
refs. Shared registration lives in etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib

from casesignal.etl.adapters.cold_case_md_wicomico.scrape import CaseRef
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = "https://www.wicomicosheriff.com/coldCases"


def register_wicomico_source(context: PipelineContext) -> None:
    refs: list[CaseRef] = context.get_metadata("wicomico_refs") or []
    if not refs:
        raise RuntimeError(
            "wicomico_refs missing from context metadata; prepare_input must run first."
        )
    register_cold_case_source(
        context,
        source_hash=canonical_refs_hash(refs),
        source_file_name=_SOURCE_URL,
        log_label="Wicomico",
    )


def canonical_refs_hash(refs: list[CaseRef]) -> str:
    """SHA256 of sorted '<source_case_id>|<case_name>' lines."""
    canonical = "\n".join(sorted(f"{r.source_case_id}|{r.case_name}" for r in refs))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

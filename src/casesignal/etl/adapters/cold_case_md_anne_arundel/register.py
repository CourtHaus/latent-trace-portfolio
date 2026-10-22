"""Source registration for Anne Arundel County, MD adapter.

source_hash = canonical sorted (source_case_id, case_name) pairs from the parsed
sections. Shared registration lives in etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib

from casesignal.etl.adapters.cold_case_md_anne_arundel.scrape import CaseSection
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = "https://www.aacounty.org/police-department/crime-information/cold-cases"


def register_aa_source(context: PipelineContext) -> None:
    sections: list[CaseSection] = context.get_metadata("aa_sections") or []
    if not sections:
        raise RuntimeError(
            "aa_sections missing from context metadata; prepare_input must run first."
        )
    register_cold_case_source(
        context,
        source_hash=canonical_sections_hash(sections),
        source_file_name=_SOURCE_URL,
        log_label="AA",
    )


def canonical_sections_hash(sections: list[CaseSection]) -> str:
    """SHA256 of sorted '<source_case_id>|<case_name>' lines."""
    canonical = "\n".join(sorted(f"{s.source_case_id}|{s.case_name}" for s in sections))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

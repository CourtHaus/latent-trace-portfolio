"""Source registration for the cold case VA (VSPCCD) adapter.

File-based: source_hash is derived from the input CSV via resolve_source_hash.
Shared file-based registration lives in etl/services/source_registration.py
(source_file_name defaults to the input file's name, as VA records it).
"""

from __future__ import annotations

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_file_based_cold_case_source


def register_cold_case_source(context: PipelineContext) -> None:
    register_file_based_cold_case_source(context, log_label="VA")

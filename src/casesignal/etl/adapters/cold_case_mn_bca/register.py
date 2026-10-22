"""MN BCA source registration.

File-based: source_hash is the SHA256 of the harvest JSON file (via
resolve_source_hash); a re-harvest with changed cases produces a new
dataset_version. Shared file-based registration lives in
etl/services/source_registration.py.
"""

from __future__ import annotations

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_file_based_cold_case_source


def register_mn_source(context: PipelineContext) -> None:
    register_file_based_cold_case_source(context, log_label="MN")

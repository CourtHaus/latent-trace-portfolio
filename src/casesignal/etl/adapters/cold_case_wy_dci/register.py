"""Source registration for the Wyoming DCI adapter.

File-based: source_hash is the SHA256 of the unified CSV (built locally by
scripts/build_wyoming_unified_csv.py). Shared file-based registration lives in
etl/services/source_registration.py.
"""

from __future__ import annotations

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_file_based_cold_case_source

# WY records the public cold-cases page as the source file (the CSV is a local
# build artifact), so override the default input-filename.
_SOURCE_FILE_NAME = "https://wyomingdci.wyo.gov/operations/cold-cases"


def register_cold_case_source(context: PipelineContext) -> None:
    register_file_based_cold_case_source(
        context, log_label="Wyoming DCI", source_file_name=_SOURCE_FILE_NAME
    )

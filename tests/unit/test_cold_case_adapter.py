"""Unit tests for the cold case VA adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from casesignal.etl.adapters.cold_case_va.adapter import ColdCaseVAAdapter
from casesignal.etl.adapters.cold_case_va.schema_baseline import (
    COLD_CASE_VA_EXPECTED_COLUMNS,
)
from casesignal.etl.services.source_definition import SourceDefinition


def test_schema_baseline_covers_all_csv_columns() -> None:
    """The baseline must list every column present in the 2025-03-27 CSV."""
    expected = {
        "_id",
        "case_name",
        "post_id",
        "type",
        "incident-date",
        "address",
        "city",
        "state",
        "vspccd-number",
        "about",
        "victim-fields_first-name",
        "victim-fields_last-name",
        "victim-fields_gender",
        "victim-fields_height",
        "victim-fields_weight",
        "victim-fields_age",
        "victim-fields_race",
        "victim-fields_eye-color",
        "victim-fields_hair-color",
        "contact-first-name",
        "contact-last-name",
        "contact-phone-number",
        "contact-address",
        "contact-email",
        "geographic-location",
    }
    assert COLD_CASE_VA_EXPECTED_COLUMNS == expected


def _make_source_definition() -> SourceDefinition:
    return SourceDefinition(
        source_key="cold_case_va_2025_03_27",
        source_family="cold_case",
        adapter_name="cold_case_va",
        source_code="VSPCCD_VA",
        source_name="Virginia VSPCCD Cold Case Database",
        input_path=Path("data/raw/cold_case_va/2025_03_27/raw_data.csv"),
        input_type="csv",
        source_year=2025,
        source_state="VA",
        description="test",
        required_files=frozenset({"raw_data.csv"}),
        optional_files=frozenset(),
        metadata={},
    )


def test_adapter_name_is_cold_case_va() -> None:
    adapter = ColdCaseVAAdapter(_make_source_definition())
    assert adapter.adapter_name == "cold_case_va"


def test_adapter_requires_csv_input_type() -> None:
    import dataclasses
    import logging

    from casesignal.etl.services.pipeline_context import PipelineContext

    source = _make_source_definition()
    # Build a non-csv source to force the rejection path
    bad_source = SourceDefinition(
        **{
            k: getattr(source, k)
            for k in (f.name for f in dataclasses.fields(source))
            if k != "input_type"
        },
        input_type="zip",
    )
    adapter = ColdCaseVAAdapter(bad_source)
    # Adapter should raise when prepare_input runs with input_type != "csv"
    # (We're only testing the adapter_name property and input-type validation here;
    # prepare_input integration is tested in Task 10.)
    ctx = PipelineContext(
        source_key=source.source_key,
        source_code=source.source_code,
        source_name=source.source_name,
        source_family=source.source_family,
        source_path=bad_source.input_path,
        source_year=bad_source.source_year,
        source_state=bad_source.source_state,
    )
    ctx.logger = logging.getLogger("test")
    with pytest.raises(ValueError, match="input_type"):
        adapter.prepare_input(ctx)

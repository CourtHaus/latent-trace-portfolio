"""Unit tests for SourceDefinition invariants, focused on the year/path guardrail."""

from __future__ import annotations

from pathlib import Path

import pytest

from casesignal.etl.services.source_definition import SourceDefinition


def _make(
    *,
    source_year: int | None = 2024,
    input_path: str | Path = "data/raw/nibrs/va/2024/nibrs_va_2024.zip",
    input_type: str = "zip",
) -> SourceDefinition:
    return SourceDefinition(
        source_key="nibrs_va_test",
        source_family="nibrs",
        adapter_name="nibrs",
        source_code="FBI_NIBRS",
        source_name="Virginia NIBRS",
        input_path=Path(input_path),
        input_type=input_type,
        source_year=source_year,
        source_state="VA",
    )


def test_source_year_matching_path_year_is_valid() -> None:
    sd = _make(source_year=2022, input_path="data/raw/nibrs/va/2022/nibrs_va_2022.zip")
    assert sd.source_year == 2022


def test_source_year_mismatching_single_path_year_raises() -> None:
    with pytest.raises(ValueError, match=r"source_year=2023.*nibrs_va_2022\.zip.*\[2022\]"):
        _make(source_year=2023, input_path="data/raw/nibrs/va/2022/nibrs_va_2022.zip")


def test_source_year_matches_one_of_multiple_years_in_path_is_valid() -> None:
    # e.g., a snapshot directory named by its year that contains a differently-dated file
    sd = _make(source_year=2020, input_path="data/raw/2020_snapshot/2020/nibrs_va_2020.zip")
    assert sd.source_year == 2020


def test_source_year_missing_from_multi_year_path_raises() -> None:
    with pytest.raises(ValueError, match=r"found: \[2020, 2022\]"):
        _make(source_year=2021, input_path="data/raw/2020_snapshot/nibrs_va_2022.zip")


def test_path_with_no_year_tokens_skips_validation() -> None:
    # When the path doesn't encode a year at all, we can't validate — pass through.
    sd = _make(source_year=2024, input_path="data/uploads/latest.zip")
    assert sd.source_year == 2024


def test_none_source_year_skips_validation() -> None:
    sd = _make(source_year=None, input_path="data/raw/nibrs/va/2022/nibrs_va_2022.zip")
    assert sd.source_year is None


def test_long_digit_run_adjacent_to_year_does_not_false_match() -> None:
    # The regex should not match 4-digit substrings inside longer digit runs.
    # e.g., "12022" should not be parsed as year 2022.
    sd = _make(source_year=2024, input_path="data/raw/v12022/nibrs_va_2024.zip")
    assert sd.source_year == 2024


def test_input_type_csv_is_accepted() -> None:
    """SourceDefinition must accept input_type='csv' for CSV-based sources (cold case)."""

    source = SourceDefinition(
        source_key="test_csv_source",
        source_family="cold_case",
        adapter_name="cold_case_va",
        source_code="TEST",
        source_name="Test CSV Source",
        input_path=Path("/tmp/test_2025.csv"),
        input_type="csv",
        source_year=2025,
        source_state="VA",
    )
    assert source.input_type == "csv"


def test_input_type_unknown_is_rejected() -> None:
    """Inputs outside the allowlist must raise with a helpful message."""
    with pytest.raises(ValueError, match=r"Unsupported input_type 'parquet'"):
        _make(input_type="parquet", input_path="data/raw/nibrs/va/2024/nibrs_va_2024.parquet")

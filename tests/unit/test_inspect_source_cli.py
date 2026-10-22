"""Unit tests for the inspect-source CLI formatter."""

from __future__ import annotations

from pathlib import Path

from casesignal.etl.runners.inspect_source import (
    exit_code_for_ready,
    format_report,
)
from casesignal.etl.services.zip_inspector import (
    DriftKind,
    DriftReport,
    FileReport,
    InspectionReport,
    ReadyStatus,
)


def _report(ready: ReadyStatus, required: list[FileReport]) -> InspectionReport:
    return InspectionReport(
        zip_path=Path("/tmp/fixture.zip"),
        file_size_bytes=12345,
        required_files=required,
        optional_files=[],
        ready=ready,
        source_key="cold_case_md_test_2022",
        source_year=2022,
        source_state="MD",
    )


def test_exit_code_for_ready_yes_is_zero() -> None:
    assert exit_code_for_ready(ReadyStatus.YES) == 0


def test_exit_code_for_ready_with_caution_is_zero() -> None:
    assert exit_code_for_ready(ReadyStatus.WITH_CAUTION) == 0


def test_exit_code_for_ready_no_is_one() -> None:
    assert exit_code_for_ready(ReadyStatus.NO) == 1


def test_format_report_shows_source_key_and_path() -> None:
    r = _report(ReadyStatus.YES, [FileReport("agencies.csv", True, 100, 10, ["agency_id"], None)])
    out = format_report(r)
    assert "cold_case_md_test_2022" in out
    assert "/tmp/fixture.zip" in out
    assert "2022" in out
    assert "MD" in out


def test_format_report_shows_ready_yes() -> None:
    r = _report(ReadyStatus.YES, [FileReport("agencies.csv", True, 100, 10, ["agency_id"], None)])
    out = format_report(r)
    assert "Ready for ingestion: YES" in out


def test_format_report_shows_ready_no_on_missing_required_file() -> None:
    r = _report(
        ReadyStatus.NO,
        [FileReport("agencies.csv", False, 0, None, None, None)],
    )
    out = format_report(r)
    assert "Ready for ingestion: NO" in out
    assert "agencies.csv" in out
    assert "MISSING" in out or "missing" in out.lower()


def test_format_report_shows_known_variant_warning() -> None:
    drift = DriftReport(
        kind=DriftKind.KNOWN_VARIANT,
        missing=frozenset({"old_column_name"}),
        extra=frozenset({"new_column_name"}),
        variant_name="test-known-variant",
    )
    r = _report(
        ReadyStatus.WITH_CAUTION,
        [FileReport("data.csv", True, 1000, 50, ["case_id", "new_column_name"], drift)],
    )
    out = format_report(r)
    assert "test-known-variant" in out
    assert "Ready for ingestion: WITH CAUTION" in out


def test_format_report_shows_missing_required_column_as_blocking() -> None:
    drift = DriftReport(
        kind=DriftKind.MISSING_REQUIRED,
        missing=frozenset({"agency_name"}),
        extra=frozenset(),
        variant_name=None,
    )
    r = _report(
        ReadyStatus.NO,
        [FileReport("agencies.csv", True, 100, 10, ["agency_id"], drift)],
    )
    out = format_report(r)
    assert "agency_name" in out
    assert "Ready for ingestion: NO" in out

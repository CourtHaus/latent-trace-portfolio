"""Unit tests for the reusable zip inspector.

These tests exercise the inspector mechanics (drift classification, basename
matching, ready status) using a synthetic baseline rather than any specific
adapter's schema. The inspector is adapter-agnostic; callers supply both the
``baseline_columns`` mapping and the optional ``variant_detector`` callable.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from casesignal.etl.services.zip_inspector import (
    DriftKind,
    InspectionReport,
    ReadyStatus,
    inspect_zip,
)


def _build_fixture_zip(tmp_path: Path, files: dict[str, str]) -> Path:
    """Build a tiny zip under tmp_path with the given {filename: content} mapping."""
    zip_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return zip_path


# Synthetic baseline used across tests. Two files modeled on a generic
# "tabular import" — agencies + offenses — to keep the tests representative
# of real adapter shapes without coupling to any specific source.
TEST_BASELINE: dict[str, frozenset[str]] = {
    "agencies.csv": frozenset({"agency_id", "agency_name", "state_abbr"}),
    "offenses.csv": frozenset({"incident_id", "offense_code", "offense_seq"}),
}

TEST_REQUIRED = ["offenses.csv", "agencies.csv"]
TEST_OPTIONAL = ["months.csv"]


def _legacy_variant_detector(filename: str, actual: frozenset[str]) -> str | None:
    """Stub variant detector: recognizes a single 'legacy' offense schema in
    which ``offense_code`` was replaced by ``offense_type_id``."""
    if filename == "offenses.csv" and "offense_type_id" in actual and "offense_code" not in actual:
        return "legacy offense-type-fk"
    return None


def _header_for(file: str, *, override: frozenset[str] | None = None) -> str:
    cols = override if override is not None else TEST_BASELINE[file]
    return ",".join(sorted(cols))


def test_inspect_zip_all_required_present_clean(tmp_path: Path) -> None:
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "agencies.csv": f"{_header_for('agencies.csv')}\nx\ny\n",
            "offenses.csv": f"{_header_for('offenses.csv')}\nrow\n",
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
    )
    assert isinstance(report, InspectionReport)
    assert report.ready == ReadyStatus.YES
    by_name = {r.filename: r for r in report.required_files}
    assert by_name["agencies.csv"].present is True
    assert by_name["agencies.csv"].row_count == 2
    assert by_name["agencies.csv"].drift is None
    assert by_name["offenses.csv"].drift is None


def test_inspect_zip_handles_directory_prefix_in_zip(tmp_path: Path) -> None:
    # Some source zips put files under a <state>/ prefix; inspector matches by basename.
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "VA/agencies.csv": f"{_header_for('agencies.csv')}\n",
            "VA/offenses.csv": f"{_header_for('offenses.csv')}\n",
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
    )
    by_name = {r.filename: r for r in report.required_files}
    assert by_name["agencies.csv"].present is True, "basename matching failed — prefix not stripped"
    assert by_name["offenses.csv"].present is True


def test_inspect_zip_missing_required_file_blocks(tmp_path: Path) -> None:
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "agencies.csv": f"{_header_for('agencies.csv')}\n",
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
    )
    assert report.ready == ReadyStatus.NO
    offenses = next(r for r in report.required_files if r.filename == "offenses.csv")
    assert offenses.present is False


def test_inspect_zip_recognizes_known_variant_via_detector(tmp_path: Path) -> None:
    # Simulate legacy schema: offense_code missing, offense_type_id extra.
    baseline_offenses = TEST_BASELINE["offenses.csv"]
    variant_cols = (baseline_offenses - {"offense_code"}) | {"offense_type_id"}
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "agencies.csv": f"{_header_for('agencies.csv')}\n",
            "offenses.csv": f"{_header_for('offenses.csv', override=variant_cols)}\n",
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
        variant_detector=_legacy_variant_detector,
    )
    offenses = next(r for r in report.required_files if r.filename == "offenses.csv")
    assert offenses.drift is not None
    assert offenses.drift.kind == DriftKind.KNOWN_VARIANT
    assert offenses.drift.variant_name == "legacy offense-type-fk"
    assert report.ready in (ReadyStatus.YES, ReadyStatus.WITH_CAUTION)


def test_inspect_zip_unknown_extra_column_warns(tmp_path: Path) -> None:
    agencies_cols = TEST_BASELINE["agencies.csv"] | {"made_up_field"}
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "agencies.csv": f"{_header_for('agencies.csv', override=agencies_cols)}\n",
            "offenses.csv": f"{_header_for('offenses.csv')}\n",
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
    )
    agencies = next(r for r in report.required_files if r.filename == "agencies.csv")
    assert agencies.drift is not None
    assert agencies.drift.kind == DriftKind.EXTRA_UNKNOWN
    assert "made_up_field" in agencies.drift.extra
    assert report.ready == ReadyStatus.WITH_CAUTION


def test_inspect_zip_missing_required_column_blocks(tmp_path: Path) -> None:
    # Baseline minus one required column, no compensating extra → MISSING_REQUIRED (blocking)
    baseline_agencies = TEST_BASELINE["agencies.csv"]
    first_col = sorted(baseline_agencies)[0]
    reduced = baseline_agencies - {first_col}
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "agencies.csv": f"{_header_for('agencies.csv', override=reduced)}\n",
            "offenses.csv": f"{_header_for('offenses.csv')}\n",
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
    )
    agencies = next(r for r in report.required_files if r.filename == "agencies.csv")
    assert agencies.drift is not None
    assert agencies.drift.kind == DriftKind.MISSING_REQUIRED
    assert first_col in agencies.drift.missing
    assert report.ready == ReadyStatus.NO


def test_inspect_zip_reports_row_count(tmp_path: Path) -> None:
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "agencies.csv": f"{_header_for('agencies.csv')}\n1\n2\n3\n",
            "offenses.csv": f"{_header_for('offenses.csv')}\n",  # header only, 0 data rows
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
    )
    agencies = next(r for r in report.required_files if r.filename == "agencies.csv")
    assert agencies.row_count == 3
    offenses = next(r for r in report.required_files if r.filename == "offenses.csv")
    assert offenses.row_count == 0


def test_inspect_zip_optional_file_missing_is_not_blocking(tmp_path: Path) -> None:
    zip_path = _build_fixture_zip(
        tmp_path,
        {
            "agencies.csv": f"{_header_for('agencies.csv')}\n",
            "offenses.csv": f"{_header_for('offenses.csv')}\n",
        },
    )
    report = inspect_zip(
        zip_path,
        required_files=TEST_REQUIRED,
        optional_files=TEST_OPTIONAL,
        baseline_columns=TEST_BASELINE,
    )
    assert report.ready == ReadyStatus.YES
    by_name = {r.filename: r for r in report.optional_files}
    assert by_name["months.csv"].present is False


def test_inspect_zip_unreadable_zip_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.zip"
    bogus.write_bytes(b"this is not a zip file")
    with pytest.raises(zipfile.BadZipFile):
        inspect_zip(bogus, required_files=TEST_REQUIRED, optional_files=TEST_OPTIONAL)

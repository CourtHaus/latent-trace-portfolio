"""Reusable logic for inspecting a source zip or CSV prior to ingestion.

Opens the input, reads CSV headers and row counts, compares headers against a
caller-supplied baseline, and classifies any drift as (a) a known variant the
adapter handles, (b) an unknown extra column (warning), or (c) a missing
required column (blocking). Returns a structured InspectionReport.

Both ``baseline_columns`` and ``variant_detector`` are caller-supplied so this
module stays adapter-agnostic. When ``baseline_columns`` is None (or has no
entry for a given file), drift detection is skipped for that file. When
``variant_detector`` is None, the inspector never produces ``KNOWN_VARIANT``
drift.

No CLI or printing in this module. The CLI wrapper lives in
src/casesignal/etl/runners/inspect_source.py.

Files inside the zip are matched by BASENAME (Path(name).name) — some source
zips have a directory prefix (e.g., VA/agencies.csv) that adapters strip
during extraction. This inspector mirrors that behavior.
"""

from __future__ import annotations

import csv
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from io import TextIOWrapper
from pathlib import Path

VariantDetector = Callable[[str, frozenset[str]], str | None]


class DriftKind(str, Enum):
    KNOWN_VARIANT = "known_variant"
    EXTRA_UNKNOWN = "extra_unknown"
    MISSING_REQUIRED = "missing_required"


class ReadyStatus(str, Enum):
    YES = "yes"
    WITH_CAUTION = "with_caution"
    NO = "no"


@dataclass(frozen=True)
class DriftReport:
    kind: DriftKind
    missing: frozenset[str]
    extra: frozenset[str]
    variant_name: str | None = None


@dataclass(frozen=True)
class FileReport:
    filename: str
    present: bool
    size_bytes: int
    row_count: int | None
    header_columns: list[str] | None
    drift: DriftReport | None


@dataclass(frozen=True)
class InspectionReport:
    zip_path: Path
    file_size_bytes: int
    required_files: list[FileReport]
    optional_files: list[FileReport]
    ready: ReadyStatus
    source_key: str | None = None
    source_year: int | None = None
    source_state: str | None = None


def inspect_zip(
    zip_path: Path,
    *,
    required_files: list[str],
    optional_files: list[str],
    source_key: str | None = None,
    source_year: int | None = None,
    source_state: str | None = None,
    baseline_columns: dict[str, frozenset[str]] | None = None,
    variant_detector: VariantDetector | None = None,
) -> InspectionReport:
    """Inspect a zip and return a structured report.

    Raises zipfile.BadZipFile if the file is not a valid zip. All semantic
    issues (missing files, missing columns, drift) are captured in the
    returned InspectionReport rather than raised.

    ``baseline_columns`` is a ``{filename: frozenset[str]}`` mapping of
    expected lowercased column names per file. Files not in the mapping skip
    drift detection. ``variant_detector`` is an optional callable that, given
    a filename and the actual lowercased column set, returns the name of a
    known schema variant or ``None``.
    """
    baseline_columns = baseline_columns or {}

    zip_path = Path(zip_path)
    file_size = zip_path.stat().st_size

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Index members by basename — mirrors adapter extraction behavior.
        # If two entries share a basename, the later one wins (deterministic).
        members_by_basename: dict[str, zipfile.ZipInfo] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            basename = Path(info.filename).name
            members_by_basename[basename] = info

        required_reports = [
            _inspect_file(
                zf,
                members_by_basename,
                name,
                is_required=True,
                baseline_columns=baseline_columns,
                variant_detector=variant_detector,
            )
            for name in required_files
        ]
        optional_reports = [
            _inspect_file(
                zf,
                members_by_basename,
                name,
                is_required=False,
                baseline_columns=baseline_columns,
                variant_detector=variant_detector,
            )
            for name in optional_files
        ]

    ready = _compute_ready(required_reports)

    return InspectionReport(
        zip_path=zip_path,
        file_size_bytes=file_size,
        required_files=required_reports,
        optional_files=optional_reports,
        ready=ready,
        source_key=source_key,
        source_year=source_year,
        source_state=source_state,
    )


def _inspect_file(
    zf: zipfile.ZipFile,
    members_by_basename: dict[str, zipfile.ZipInfo],
    filename: str,
    *,
    is_required: bool,
    baseline_columns: dict[str, frozenset[str]],
    variant_detector: VariantDetector | None,
) -> FileReport:
    info = members_by_basename.get(filename)
    if info is None:
        return FileReport(
            filename=filename,
            present=False,
            size_bytes=0,
            row_count=None,
            header_columns=None,
            drift=None,
        )

    header, row_count = _read_header_and_rowcount(zf, info)
    drift = _classify_drift(
        filename,
        header,
        is_required=is_required,
        baseline_columns=baseline_columns,
        variant_detector=variant_detector,
    )

    return FileReport(
        filename=filename,
        present=True,
        size_bytes=info.file_size,
        row_count=row_count,
        header_columns=header,
        drift=drift,
    )


def _read_header_and_rowcount(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> tuple[list[str], int]:
    with zf.open(info) as raw:
        with TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="") as text:
            reader = csv.reader(text)
            try:
                header = next(reader)
            except StopIteration:
                return [], 0
            row_count = sum(1 for _ in reader)
    return header, row_count


def _classify_drift(
    filename: str,
    header: list[str],
    *,
    is_required: bool,
    baseline_columns: dict[str, frozenset[str]],
    variant_detector: VariantDetector | None,
) -> DriftReport | None:
    baseline = baseline_columns.get(filename)
    if baseline is None:
        return None

    actual = frozenset(col.strip().lower() for col in header)
    missing = baseline - actual
    extra = actual - baseline

    if not missing and not extra:
        return None

    variant_name: str | None = None
    if variant_detector is not None:
        variant_name = variant_detector(filename, actual)

    if variant_name is not None:
        return DriftReport(
            kind=DriftKind.KNOWN_VARIANT,
            missing=missing,
            extra=extra,
            variant_name=variant_name,
        )

    if missing and is_required:
        return DriftReport(
            kind=DriftKind.MISSING_REQUIRED,
            missing=missing,
            extra=extra,
            variant_name=None,
        )

    if extra:
        return DriftReport(
            kind=DriftKind.EXTRA_UNKNOWN,
            missing=missing,
            extra=extra,
            variant_name=None,
        )

    return None


def inspect_csv(
    csv_path: Path,
    *,
    source_key: str | None = None,
    source_year: int | None = None,
    source_state: str | None = None,
    baseline_columns: dict[str, frozenset[str]] | None = None,
    variant_detector: VariantDetector | None = None,
) -> InspectionReport:
    """Inspect a plain CSV file and return a structured report.

    Used for sources whose ``input_type`` is ``"csv"`` rather than ``"zip"``.
    The CSV filename (basename) is treated as the single required file, so
    the caller should pass ``baseline_columns`` keyed by that basename.

    Raises ``FileNotFoundError`` if the CSV does not exist.
    """
    baseline_columns = baseline_columns or {}

    csv_path = Path(csv_path)
    file_size = csv_path.stat().st_size
    filename = csv_path.name

    header, row_count = _read_csv_header_and_rowcount(csv_path)
    # Strip UTF-8 BOM from first column name if present.
    if header:
        header[0] = header[0].lstrip("﻿")
    drift = _classify_drift(
        filename,
        header,
        is_required=True,
        baseline_columns=baseline_columns,
        variant_detector=variant_detector,
    )

    file_report = FileReport(
        filename=filename,
        present=True,
        size_bytes=file_size,
        row_count=row_count,
        header_columns=header,
        drift=drift,
    )
    ready = _compute_ready([file_report])

    return InspectionReport(
        zip_path=csv_path,
        file_size_bytes=file_size,
        required_files=[file_report],
        optional_files=[],
        ready=ready,
        source_key=source_key,
        source_year=source_year,
        source_state=source_state,
    )


def _read_csv_header_and_rowcount(csv_path: Path) -> tuple[list[str], int]:
    with csv_path.open(encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return [], 0
        row_count = sum(1 for _ in reader)
    return header, row_count


def _compute_ready(required_reports: list[FileReport]) -> ReadyStatus:
    has_missing_file = any(not r.present for r in required_reports)
    has_blocking_drift = any(
        r.drift is not None and r.drift.kind == DriftKind.MISSING_REQUIRED for r in required_reports
    )
    has_warning_drift = any(
        r.drift is not None and r.drift.kind in (DriftKind.KNOWN_VARIANT, DriftKind.EXTRA_UNKNOWN)
        for r in required_reports
    )
    if has_missing_file or has_blocking_drift:
        return ReadyStatus.NO
    if has_warning_drift:
        return ReadyStatus.WITH_CAUTION
    return ReadyStatus.YES

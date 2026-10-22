"""CLI: casesignal-etl-inspect <source_key>.

Thin wrapper over zip_inspector. Resolves source_key via the source catalog,
formats the InspectionReport for the terminal, and exits 0 on
YES/WITH_CAUTION or 1 on NO.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from casesignal.etl.adapters.cold_case_va.schema_baseline import (
    COLD_CASE_VA_EXPECTED_COLUMNS,
)
from casesignal.etl.services.source_catalog import SourceCatalog
from casesignal.etl.services.zip_inspector import (
    DriftKind,
    FileReport,
    InspectionReport,
    ReadyStatus,
    inspect_csv,
    inspect_zip,
)

_ADAPTER_BASELINE: dict[str, dict[str, frozenset[str]]] = {
    "cold_case_va": {"raw_data.csv": COLD_CASE_VA_EXPECTED_COLUMNS},
}

_DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[1] / "sources"


def exit_code_for_ready(ready: ReadyStatus) -> int:
    return 1 if ready == ReadyStatus.NO else 0


def format_report(report: InspectionReport) -> str:
    lines: list[str] = []
    header = f"{report.source_key or '(ad-hoc)'} ({report.zip_path}, {_human_size(report.file_size_bytes)})"
    lines.append(header)
    if report.source_year is not None or report.source_state is not None:
        lines.append(f"  source_year: {report.source_year}, source_state: {report.source_state}")
    lines.append("")

    present_req = sum(1 for r in report.required_files if r.present)
    total_req = len(report.required_files)
    lines.append(f"  Required files ({present_req}/{total_req} present):")
    for fr in report.required_files:
        lines.extend(_format_file_report(fr, indent="    "))

    if report.optional_files:
        lines.append("")
        lines.append("  Optional files:")
        for fr in report.optional_files:
            status = "PRESENT" if fr.present else "MISSING (not blocking)"
            size = _human_size(fr.size_bytes) if fr.present else ""
            row = f", {fr.row_count} rows" if fr.row_count is not None else ""
            suffix = f" ({size}{row})" if fr.present else ""
            lines.append(f"    {fr.filename:<30} {status}{suffix}")

    warnings = [
        fr
        for fr in report.required_files
        if fr.drift and fr.drift.kind != DriftKind.MISSING_REQUIRED
    ]
    blocking = [
        fr
        for fr in report.required_files
        if fr.drift and fr.drift.kind == DriftKind.MISSING_REQUIRED
    ]

    lines.append("")
    if warnings:
        lines.append("  Warnings:")
        for fr in warnings:
            assert fr.drift is not None
            if fr.drift.kind == DriftKind.KNOWN_VARIANT:
                lines.append(f"    {fr.filename}: {fr.drift.variant_name}")
                lines.append("      → handled by current adapter")
            else:
                lines.append(f"    {fr.filename}: unknown extra columns {sorted(fr.drift.extra)}")
                lines.append("      → investigate before ingestion")
    else:
        lines.append("  Warnings: (none)")

    lines.append("")
    if blocking:
        lines.append("  Schema drift (blocking):")
        for fr in blocking:
            assert fr.drift is not None
            lines.append(f"    {fr.filename}: missing required columns {sorted(fr.drift.missing)}")
            lines.append("      → adapter will fail at parse time; fix before ingestion")
    else:
        lines.append("  Schema drift (blocking): (none)")

    lines.append("")
    ready_label = {
        ReadyStatus.YES: "YES",
        ReadyStatus.WITH_CAUTION: "WITH CAUTION",
        ReadyStatus.NO: "NO",
    }[report.ready]
    lines.append(f"  Ready for ingestion: {ready_label}")

    return "\n".join(lines)


def _format_file_report(fr: FileReport, indent: str) -> list[str]:
    if not fr.present:
        return [f"{indent}{fr.filename:<30} MISSING"]
    size = _human_size(fr.size_bytes)
    rows = f"{fr.row_count:,} rows" if fr.row_count is not None else "unknown rows"
    head = fr.header_columns or []
    head_preview = ", ".join(head[:6]) + (", ..." if len(head) > 6 else "")
    out = [f"{indent}{fr.filename:<30} {size}, {rows}"]
    out.append(f"{indent}  [{head_preview}]")
    return out


def _human_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f}{unit}" if unit != "B" else f"{n_bytes}B"
        n_bytes //= 1024
    return f"{n_bytes}TB"


def _inspect_by_source_key(source_key: str, catalog_path: Path) -> InspectionReport:
    catalog = SourceCatalog.from_yaml(catalog_path)
    sd = catalog.get(source_key)
    baseline = _ADAPTER_BASELINE.get(sd.adapter_name)
    if sd.input_type == "url":
        # URL-based scrape sources don't have a local file to inspect; the
        # adapter validates reachability + page structure at run time during
        # prepare_input. Emit a metadata-only report (no file inspection).
        from casesignal.etl.services.zip_inspector import (
            InspectionReport,
            ReadyStatus,
        )

        return InspectionReport(
            zip_path=Path(str(sd.input_path)),
            file_size_bytes=0,
            required_files=[],
            optional_files=[],
            ready=ReadyStatus.YES,
            source_key=sd.source_key,
            source_year=sd.source_year,
            source_state=sd.source_state,
        )
    if sd.input_type == "csv":
        return inspect_csv(
            Path(sd.input_path),
            source_key=sd.source_key,
            source_year=sd.source_year,
            source_state=sd.source_state,
            baseline_columns=baseline,
        )
    return inspect_zip(
        Path(sd.input_path),
        required_files=sorted(sd.required_files),
        optional_files=sorted(sd.optional_files),
        source_key=sd.source_key,
        source_year=sd.source_year,
        source_state=sd.source_state,
        baseline_columns=baseline,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="casesignal-etl-inspect",
        description="Pre-flight inspection of a configured source for drift and completeness.",
    )
    parser.add_argument(
        "source_key",
        help="source_key declared in sources.yaml (e.g., cold_case_va_2025_03_27)",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=_DEFAULT_CATALOG_PATH,
        help="Path to sources.yaml (default: bundled catalog)",
    )
    args = parser.parse_args(argv)

    report = _inspect_by_source_key(args.source_key, args.catalog)

    print(format_report(report))
    return exit_code_for_ready(report.ready)


if __name__ == "__main__":
    sys.exit(main())

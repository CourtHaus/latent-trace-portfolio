"""Unit tests for the promote-demographics CLI argument surface."""

from __future__ import annotations

from casesignal.extraction.cold_case.promote_demographics import parse_args


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.case_id is None
    assert args.dry_run is False


def test_parse_args_case_id_and_dry_run() -> None:
    args = parse_args(["--case-id", "42", "--dry-run"])
    assert args.case_id == 42
    assert args.dry_run is True

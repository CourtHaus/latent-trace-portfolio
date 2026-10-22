"""Safety-gate tests for the republish_from_raw runner.

This runner DELETES cold_case.cases rows, so the guard rails matter more than
the happy path: it must refuse to act when the dataset_version belongs to a
different source, when the raw table is missing/empty, or in --dry-run mode —
and must NOT delete anything in those cases.

The DB-touching helpers are monkeypatched; we assert the control flow and that
the destructive step (`_delete_partial_cases`) fires only when every gate
passes.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import casesignal.etl.runners.republish_from_raw as rr
from casesignal.etl.runners.run_pipeline import DEFAULT_CATALOG_PATH

_LOGGER = logging.getLogger("test-republish")


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner_code: str | None,
    raw_table: str | None,
    raw_rows: int,
    partial_cases: int,
    source_code: str = "BCI_UT_PD",
    status: str = "failed",
) -> tuple[MagicMock, MagicMock]:
    """Patch every external seam of republish(); return (delete_spy, adapter)."""
    source_def = SimpleNamespace(source_code=source_code)
    context = MagicMock(name="context")
    adapter = MagicMock(name="adapter")
    registry = MagicMock(name="registry")
    registry.create_adapter.return_value = adapter

    monkeypatch.setattr(rr, "resolve_source_definition", MagicMock(return_value=source_def))
    monkeypatch.setattr(rr, "build_pipeline_context", MagicMock(return_value=context))
    monkeypatch.setattr(rr, "build_adapter_registry", MagicMock(return_value=registry))
    monkeypatch.setattr(rr, "attach_database", MagicMock())
    monkeypatch.setattr(rr, "cleanup_context", MagicMock())
    monkeypatch.setattr(rr, "_require_session_factory", MagicMock(return_value=MagicMock()))
    meta = None if owner_code is None else (owner_code, status)
    monkeypatch.setattr(rr, "_dataset_version_meta", MagicMock(return_value=meta))
    monkeypatch.setattr(rr, "_find_raw_table", MagicMock(return_value=raw_table))

    # _count is called for raw_rows then partial_cases, in that order.
    monkeypatch.setattr(rr, "_count", MagicMock(side_effect=[raw_rows, partial_cases]))

    delete_spy = MagicMock(return_value=partial_cases)
    monkeypatch.setattr(rr, "_delete_partial_cases", delete_spy)
    monkeypatch.setattr(rr, "_open_ingestion_run", MagicMock(return_value=999))
    monkeypatch.setattr(rr, "normalize_dataset_stage", MagicMock())
    return delete_spy, adapter


def _run(dry_run: bool = False, assume_yes: bool = True) -> int:
    return rr.republish(
        source_key="cold_case_ut_2026_05_11",
        dataset_version_id=363,
        catalog_path=DEFAULT_CATALOG_PATH,
        dry_run=dry_run,
        assume_yes=assume_yes,
        logger=_LOGGER,
    )


def test_refuses_when_dataset_version_belongs_to_other_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_spy, adapter = _wire(
        monkeypatch, owner_code="BCI_OH_AG", raw_table="cold_case_ut_dv363", raw_rows=207, partial_cases=207
    )
    assert _run() == 2
    delete_spy.assert_not_called()
    adapter.run_stage.assert_not_called()


def test_refuses_when_dataset_version_is_published(monkeypatch: pytest.MonkeyPatch) -> None:
    # A typo'd-but-valid dvid that is already published must NOT be rebuilt —
    # that would delete its live cases + enrichments. Only 'failed' is allowed.
    delete_spy, adapter = _wire(
        monkeypatch,
        owner_code="BCI_UT_PD",
        raw_table="cold_case_ut_dv363",
        raw_rows=207,
        partial_cases=207,
        status="published",
    )
    assert _run() == 2
    delete_spy.assert_not_called()
    adapter.run_stage.assert_not_called()


def test_refuses_when_dataset_version_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_spy, adapter = _wire(
        monkeypatch, owner_code=None, raw_table=None, raw_rows=0, partial_cases=0
    )
    assert _run() == 2
    delete_spy.assert_not_called()


def test_refuses_when_raw_table_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_spy, adapter = _wire(
        monkeypatch, owner_code="BCI_UT_PD", raw_table=None, raw_rows=0, partial_cases=207
    )
    assert _run() == 2
    delete_spy.assert_not_called()
    adapter.run_stage.assert_not_called()


def test_refuses_when_raw_table_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_spy, _ = _wire(
        monkeypatch, owner_code="BCI_UT_PD", raw_table="cold_case_ut_dv363", raw_rows=0, partial_cases=207
    )
    assert _run() == 2
    delete_spy.assert_not_called()


def test_dry_run_makes_no_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_spy, adapter = _wire(
        monkeypatch, owner_code="BCI_UT_PD", raw_table="cold_case_ut_dv363", raw_rows=207, partial_cases=207
    )
    assert _run(dry_run=True) == 0
    delete_spy.assert_not_called()
    adapter.run_stage.assert_not_called()


def test_refuses_without_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    delete_spy, adapter = _wire(
        monkeypatch, owner_code="BCI_UT_PD", raw_table="cold_case_ut_dv363", raw_rows=207, partial_cases=207
    )
    assert _run(assume_yes=False) == 2
    delete_spy.assert_not_called()
    adapter.run_stage.assert_not_called()


def test_happy_path_deletes_then_runs_three_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    # _count is hit a third time for the final published-count log line.
    delete_spy, adapter = _wire(
        monkeypatch, owner_code="BCI_UT_PD", raw_table="cold_case_ut_dv363", raw_rows=207, partial_cases=207
    )
    monkeypatch.setattr(rr, "_count", MagicMock(side_effect=[207, 207, 207]))
    assert _run() == 0
    delete_spy.assert_called_once()
    # transform -> normalize -> publish
    assert adapter.run_stage.call_count == 3
    stage_names = [c.args[1] for c in adapter.run_stage.call_args_list]
    assert stage_names == ["transform", "normalize", "publish"]

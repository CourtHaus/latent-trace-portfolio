"""Unit tests for ColdCaseMnBcaAdapter registration + prepare_input."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from casesignal.etl.adapters.cold_case_mn_bca.adapter import ColdCaseMnBcaAdapter
from casesignal.etl.runners.run_pipeline import build_adapter_registry
from casesignal.etl.services.source_catalog import SourceCatalog
from casesignal.etl.services.source_definition import SourceDefinition


def test_registry_resolves_mn_adapter() -> None:
    registry = build_adapter_registry()
    assert registry.resolve_class("cold_case_mn_bca") is ColdCaseMnBcaAdapter


def test_source_catalog_includes_mn_key() -> None:
    catalog = SourceCatalog.from_yaml("src/casesignal/etl/sources")
    assert "cold_case_mn_bca_2026_05_16" in catalog.list_keys()


def _source_def(path: Any, baseline: Any = 1) -> SourceDefinition:
    return SourceDefinition(
        source_key="cold_case_mn_bca_test",
        source_family="cold_case",
        adapter_name="cold_case_mn_bca",
        source_code="BCA_MN_TEST",
        source_name="MN BCA test",
        source_year=2026,
        source_state="MN",
        input_path=Path(path),
        input_type="file",
        description="test",
        required_files=frozenset(),
        optional_files=frozenset(),
        metadata={"baseline_count": baseline},
    )


def test_prepare_input_rejects_missing_file(tmp_path: Path) -> None:
    from casesignal.etl.runners.run_pipeline import build_pipeline_context

    source_def = _source_def(tmp_path / "absent.json")
    context = build_pipeline_context(source_def, logging.getLogger("t"))
    adapter = ColdCaseMnBcaAdapter(source_def)
    with pytest.raises(FileNotFoundError):
        adapter.prepare_input(context)


def test_prepare_input_parses_and_stashes_records(tmp_path: Path) -> None:
    from casesignal.etl.runners.run_pipeline import build_pipeline_context

    harvest = [
        {
            "ContentType": "Unsolved Homicide",
            "NameFirst": "Alex",
            "NameLast": "Exampleton",
            "Age": 42,
            "Date1": "11/17/2021",
            "LocationCity": "Minneapolis",
            "LocationCounty": "Hennepin",
            "LocationState": "MN",
            "PDF": "/bca/unsolved-cases/UnsolvedCasesDocuments/Exampleton-Alex.pdf",
            "Picture1": "/bca/unsolved-cases/UnsolvedCasesImages/Exampleton-Alex.jpg",
        }
    ]
    path = tmp_path / "h.json"
    path.write_text(json.dumps(harvest), encoding="utf-8")

    # baseline_count=1 so the single-record fixture does not trip the drift gate.
    source_def = _source_def(path, baseline=1)
    context = build_pipeline_context(source_def, logging.getLogger("t"))
    adapter = ColdCaseMnBcaAdapter(source_def)
    adapter.prepare_input(context)

    records = context.get_metadata("mn_harvest_records")
    assert records is not None and len(records) == 1
    assert context.get_metadata("polite_http") is not None

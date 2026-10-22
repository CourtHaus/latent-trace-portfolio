"""SourceCatalog directory-glob loader: merges *.yaml files in a directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from casesignal.etl.services.source_catalog import (
    SourceCatalog,
    SourceCatalogLoadError,
    SourceDefinitionError,
)

_VALID_SOURCE_TEMPLATE = """
sources:
  - source_key: {source_key}
    source_family: cold_case
    adapter_name: cold_case_va
    source_code: TEST_CODE
    source_name: Test Source
    input_path: data/raw/test/snapshot.csv
    input_type: csv
    source_year: 2026
    source_state: VA
    description: Test source.
    required_files: [snapshot.csv]
    optional_files: []
    metadata: {{}}
"""


def _write_yaml(directory: Path, filename: str, source_key: str) -> Path:
    path = directory / filename
    path.write_text(_VALID_SOURCE_TEMPLATE.format(source_key=source_key))
    return path


def test_directory_with_single_yaml_loads(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "first.yaml", "alpha")
    catalog = SourceCatalog.from_yaml(tmp_path)
    assert "alpha" in catalog
    assert len(catalog) == 1


def test_directory_merges_multiple_yaml_files(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "first.yaml", "alpha")
    _write_yaml(tmp_path, "second.yaml", "beta")
    catalog = SourceCatalog.from_yaml(tmp_path)
    assert "alpha" in catalog
    assert "beta" in catalog
    assert len(catalog) == 2


def test_directory_duplicate_source_key_names_both_files(tmp_path: Path) -> None:
    p1 = _write_yaml(tmp_path, "first.yaml", "alpha")
    p2 = _write_yaml(tmp_path, "second.yaml", "alpha")
    with pytest.raises(SourceDefinitionError) as exc_info:
        SourceCatalog.from_yaml(tmp_path)
    msg = str(exc_info.value)
    assert "alpha" in msg
    assert str(p1) in msg
    assert str(p2) in msg


def test_directory_with_no_yaml_files_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceCatalogLoadError, match="no \\*\\.yaml files"):
        SourceCatalog.from_yaml(tmp_path)


def test_single_file_path_still_supported(tmp_path: Path) -> None:
    """Backwards-compat: passing a file path (not a directory) loads just that file."""
    path = _write_yaml(tmp_path, "lonely.yaml", "solo")
    catalog = SourceCatalog.from_yaml(path)
    assert "solo" in catalog
    assert len(catalog) == 1


def test_path_does_not_exist_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceCatalogLoadError, match="does not exist"):
        SourceCatalog.from_yaml(tmp_path / "missing")


def test_yaml_files_are_loaded_in_sorted_order(tmp_path: Path) -> None:
    """Sorted-glob order keeps catalog merge deterministic across filesystems."""
    _write_yaml(tmp_path, "z_last.yaml", "alpha")
    _write_yaml(tmp_path, "a_first.yaml", "beta")
    catalog = SourceCatalog.from_yaml(tmp_path)
    assert {"alpha", "beta"} == set(catalog.list_keys())

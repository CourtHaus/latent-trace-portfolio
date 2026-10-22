"""Validation loader contracts using an explicitly synthetic YAML example."""
from pathlib import Path

import pytest

from casesignal.extraction.cold_case import validation


def test_load_synthetic_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    labels = tmp_path / "labels.yaml"
    labels.write_text("""labels:
  - state: VA
    source_case_id: synthetic-001
    weapon:
      value: firearm
      verbatim_phrase: a firearm
    location_type:
      value: unknown
      verbatim_phrase: null
""")
    monkeypatch.setattr(validation, "VALIDATION_LABELS_PATH", labels)
    result = validation.load_validation_labels()
    assert len(result) == 1
    assert result[0].key == "VA:synthetic-001"
    assert result[0].weapon == validation.FieldLabel("firearm", "a firearm")
    assert result[0].location_type == validation.FieldLabel("unknown", None)


def test_missing_labels_fail_explicitly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validation, "VALIDATION_LABELS_PATH", tmp_path / "missing.yaml")
    with pytest.raises(FileNotFoundError):
        validation.load_validation_labels()

"""Load the hand-labeled validation set from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATION_LABELS_PATH = _REPO_ROOT / "data" / "validation" / "cold_case_extraction_labels.yaml"


@dataclass(frozen=True)
class FieldLabel:
    value: str  # enum value (including "unknown")
    verbatim_phrase: str | None  # None when value == "unknown"


@dataclass(frozen=True)
class ValidationLabel:
    state: str
    source_case_id: str
    weapon: FieldLabel
    location_type: FieldLabel

    @property
    def key(self) -> str:
        """Stable join key into the recorded-responses fixture. (state,
        source_case_id) survives re-ingests; the serial case_id does not."""
        return f"{self.state}:{self.source_case_id}"


def load_validation_labels() -> list[ValidationLabel]:
    """Return all validation labels from the fixtures file."""
    data = yaml.safe_load(VALIDATION_LABELS_PATH.read_text(encoding="utf-8"))
    labels: list[ValidationLabel] = []
    for entry in data["labels"]:
        labels.append(
            ValidationLabel(
                state=entry["state"],
                source_case_id=str(entry["source_case_id"]),
                weapon=FieldLabel(
                    value=entry["weapon"]["value"],
                    verbatim_phrase=entry["weapon"].get("verbatim_phrase"),
                ),
                location_type=FieldLabel(
                    value=entry["location_type"]["value"],
                    verbatim_phrase=entry["location_type"].get("verbatim_phrase"),
                ),
            )
        )
    return labels

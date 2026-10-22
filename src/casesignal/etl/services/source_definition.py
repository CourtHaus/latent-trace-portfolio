from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_YEAR_IN_PATH_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


@dataclass(slots=True, frozen=True)
class SourceDefinition:
    """
    Generic definition of an ingestible source dataset.

    This object represents one concrete dataset instance that can be processed
    by the ingestion framework.
    """

    source_key: str
    source_family: str
    adapter_name: str
    source_code: str
    source_name: str

    input_path: Path
    input_type: str  # expected values: "zip", "directory", "file", "csv"

    source_year: int | None = None
    source_state: str | None = None

    required_files: frozenset[str] = field(default_factory=frozenset)
    optional_files: frozenset[str] = field(default_factory=frozenset)

    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_path", Path(self.input_path))

        if not self.source_key.strip():
            raise ValueError("source_key must be non-empty.")

        if not self.source_family.strip():
            raise ValueError("source_family must be non-empty.")

        if not self.adapter_name.strip():
            raise ValueError("adapter_name must be non-empty.")

        if not self.source_code.strip():
            raise ValueError("source_code must be non-empty.")

        if not self.source_name.strip():
            raise ValueError("source_name must be non-empty.")

        if self.input_type not in {"zip", "directory", "file", "csv", "url"}:
            raise ValueError(
                f"Unsupported input_type '{self.input_type}' for source_key '{self.source_key}'."
                "Expected one of: 'zip', 'directory', 'file', 'csv', 'url'."
            )

        if self.source_year is not None and not (1900 <= self.source_year <= 2100):
            raise ValueError(
                f"Invalid source_year '{self.source_year}' for source_key '{self.source_key}'."
            )

        if self.source_state is not None and not self.source_state.strip():
            raise ValueError("source_state cannot be blank if provided.")

        if self.source_year is not None:
            years_in_path = {int(match) for match in _YEAR_IN_PATH_RE.findall(str(self.input_path))}
            if years_in_path and self.source_year not in years_in_path:
                raise ValueError(
                    f"source_year={self.source_year} for source_key "
                    f"'{self.source_key}' does not match any year found in "
                    f"input_path='{self.input_path}' (found: "
                    f"{sorted(years_in_path)}). If input_path genuinely does "
                    "not encode the source year, rename the file so the year "
                    "is not ambiguous, or remove the conflicting digits."
                )

    @property
    def source_label(self) -> str:
        """
        Human-readable source label for logging and diagnostics.
        """
        parts = [self.source_name]

        if self.source_state:
            parts.append(self.source_state)

        if self.source_year is not None:
            parts.append(str(self.source_year))

        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """
        :return: A structured dictionary representation suitable for logging.
        """

        return {
            "source_key": self.source_key,
            "source_family": self.source_family,
            "adapter_name": self.adapter_name,
            "source_code": self.source_code,
            "source_name": self.source_name,
            "source_label": self.source_label,
            "input_path": str(self.input_path),
            "input_type": self.input_type,
            "source_year": self.source_year,
            "source_state": self.source_state,
            "required_files": sorted(self.required_files),
            "optional_files": sorted(self.optional_files),
            "description": self.description,
            "metadata": self.metadata,
        }

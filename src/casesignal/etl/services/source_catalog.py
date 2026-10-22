from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from casesignal.etl.services.source_definition import SourceDefinition


class SourceCatalogLoadError(Exception):
    """Raised when the source catalog cannot be loaded or parsed."""


class SourceDefinitionError(Exception):
    """Raised when a source definition is missing required fields or is invalid."""


class SourceCatalog:
    """
    In-memory registry of SourceDefinition objects loaded from a declarative catalog.

    The catalog is keyed by `source_key` and is intended to be the single source of truth
    for resolving which dataset instance the pipeline should process.
    """

    def __init__(self, sources: dict[str, SourceDefinition]) -> None:
        self._sources = sources

    @classmethod
    def from_yaml(cls, catalog_path: str | Path) -> SourceCatalog:
        """Load a SourceCatalog from a YAML file OR a directory of YAML files.

        If `catalog_path` is a directory, every `*.yaml` file inside is parsed
        and their `sources:` lists are merged into a single catalog. Source-key
        uniqueness is enforced across the merged set; on collision, the error
        message names both source files.

        If `catalog_path` is a file, only that file is parsed (single-file mode,
        kept for tests that construct ad-hoc catalogs in temp dirs).
        """
        path = Path(catalog_path)

        if not path.exists():
            raise SourceCatalogLoadError(f"Source catalog path does not exist: {path}")

        if path.is_dir():
            yaml_files = sorted(path.glob("*.yaml"))
            if not yaml_files:
                raise SourceCatalogLoadError(
                    f"Source catalog directory contains no *.yaml files: {path}"
                )
            return cls._from_yaml_files(yaml_files)

        if not path.is_file():
            raise SourceCatalogLoadError(
                f"Source catalog path is neither a file nor a directory: {path}"
            )

        return cls._from_yaml_files([path])

    @classmethod
    def _from_yaml_files(cls, paths: list[Path]) -> SourceCatalog:
        """Parse one or more YAML files and merge their `sources:` lists.

        Internal helper used by both directory-mode and single-file-mode of
        `from_yaml`.
        """
        sources: dict[str, SourceDefinition] = {}
        # source_key -> originating file path, for duplicate-error reporting
        provenance: dict[str, Path] = {}

        for path in paths:
            try:
                with path.open("r", encoding="utf-8") as f:
                    raw_catalog = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                raise SourceCatalogLoadError(
                    f"Failed to parse YAML source catalog: {path}"
                ) from exc
            except OSError as exc:
                raise SourceCatalogLoadError(f"Failed to read source catalog file: {path}") from exc

            if raw_catalog is None:
                raise SourceCatalogLoadError(f"Source catalog is empty: {path}")

            if not isinstance(raw_catalog, dict):
                raise SourceCatalogLoadError(
                    f"Source catalog root must be a mapping/object: {path}"
                )

            raw_sources = raw_catalog.get("sources")
            if raw_sources is None:
                raise SourceCatalogLoadError(
                    f"Source catalog is missing required top-level key 'sources': {path}"
                )

            if not isinstance(raw_sources, list):
                raise SourceCatalogLoadError(
                    f"Source catalog key 'sources' must contain a list: {path}"
                )

            for index, raw_source in enumerate(raw_sources):
                source = cls._build_source_definition(raw_source=raw_source, index=index)
                if source.source_key in sources:
                    other = provenance[source.source_key]
                    raise SourceDefinitionError(
                        f"Duplicate source_key '{source.source_key}' across catalog files: "
                        f"{other} and {path}"
                    )
                sources[source.source_key] = source
                provenance[source.source_key] = path

        return cls(sources=sources)

    @staticmethod
    def _build_source_definition(
        raw_source: dict[str, Any],
        index: int,
    ) -> SourceDefinition:
        """
        Convert one raw YAML mapping into a validated SourceDefintion.
        """
        if not isinstance(raw_source, dict):
            raise SourceDefinitionError(f"Source entry at index {index} must be a mapping/object.")

        required_fields = {
            "source_key",
            "source_family",
            "adapter_name",
            "source_code",
            "source_name",
            "input_path",
            "input_type",
        }

        missing_fields = sorted(field for field in required_fields if field not in raw_source)
        if missing_fields:
            raise SourceDefinitionError(
                f"Source entry at index {index} is missing required fields: "
                f"{', '.join(missing_fields)}"
            )

        required_files = raw_source.get("required_files") or []
        optional_files = raw_source.get("optional_files") or []
        metadata = raw_source.get("metadata") or {}

        if not isinstance(required_files, list):
            raise SourceDefinitionError(
                f"'required_files' must be a list for source '{raw_source.get('source_key', index)}'."
            )

        if not isinstance(optional_files, list):
            raise SourceDefinitionError(
                f"'optional_files' must be a list for source '{raw_source.get('source_key', index)}'."
            )

        if not isinstance(metadata, dict):
            raise SourceDefinitionError(
                f"'metadata' must be a mapping/object for source '{raw_source.get('source_key', index)}'."
            )

        try:
            return SourceDefinition(
                source_key=str(raw_source["source_key"]),
                source_family=str(raw_source["source_family"]),
                adapter_name=str(raw_source["adapter_name"]),
                source_code=str(raw_source["source_code"]),
                source_name=str(raw_source["source_name"]),
                input_path=Path(str(raw_source["input_path"])),
                input_type=str(raw_source["input_type"]),
                source_year=raw_source.get("source_year"),
                source_state=raw_source.get("source_state"),
                required_files=frozenset(str(item) for item in required_files),
                optional_files=frozenset(str(item) for item in optional_files),
                description=raw_source.get("description"),
                metadata=metadata,
            )
        except Exception as exc:
            source_key = raw_source.get("source_key", f"index {index}")
            raise SourceDefinitionError(
                f"Failed to build SourceDefinition for source '{source_key}'."
            ) from exc

    def get(self, source_key: str) -> SourceDefinition:
        """Retrieve a source definition by source_key."""

        try:
            return self._sources[source_key]
        except KeyError as exc:
            available = ", ".join(sorted(self._sources))
            raise KeyError(
                f"Unknown source_key '{source_key}'. Available source keys: {available}"
            ) from exc

    def list_keys(self) -> list[str]:
        return sorted(self._sources)

    def list_sources(self) -> list[SourceDefinition]:
        return [self._sources[key] for key in self.list_keys()]

    def __contains__(self, source_key: object) -> bool:
        return source_key in self._sources

    def __len__(self) -> int:
        return len(self._sources)

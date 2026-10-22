from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024


def resolve_source_hash(
    source_path: Path,
    metadata: Mapping[str, Any] | None = None,
) -> str | None:
    """
    Resolve a stable content hash for the source artifact.

    Preference order:
    1. explicit source_hash supplied in metadata
    2. hash of the input file bytes
    3. deterministic recursive hash of directory contents
    """
    if metadata is not None:
        provided_hash = metadata.get("source_hash")
        if isinstance(provided_hash, str) and provided_hash.strip():
            return provided_hash.strip()

    if source_path.is_file():
        return _hash_file(source_path)

    if source_path.is_dir():
        return _hash_directory(source_path)

    return None


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)

    return hasher.hexdigest()


def _hash_directory(directory: Path) -> str:
    hasher = hashlib.sha256()

    for path in sorted(candidate for candidate in directory.rglob("*") if candidate.is_file()):
        relative_path = path.relative_to(directory).as_posix().encode("utf-8")
        hasher.update(len(relative_path).to_bytes(8, byteorder="big", signed=False))
        hasher.update(relative_path)
        hasher.update(path.stat().st_size.to_bytes(8, byteorder="big", signed=False))

        with path.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)

    return hasher.hexdigest()

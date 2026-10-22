"""Pure-function photo handling helpers shared by ETL adapters.

Hashing + filename sanitization + the canonical content-type→extension
map are used by every raw_load.py that downloads photos. Previously
they were duplicated byte-for-byte across 5+ adapters.

Pure functions only — no DB, no I/O orchestration beyond reading the
file for hashing. Callers handle persistence + photo placement.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Canonical content-type → file-extension map. Superset of the per-adapter
# variations observed in the corpus:
# - image/jpeg + image/pjpeg both map to jpg (the latter is legacy IE-era
#   progressive JPEG; OH AG and NH DOJ both serve it)
# - image/bmp seen on a small slice of OH AG photos
# - image/webp included for completeness; modern CMSs serve it
PHOTO_EXT_BY_CONTENT_TYPE: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/pjpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
}


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(raw: str) -> str:
    """Sanitize a source-supplied filename for local disk storage.

    Substitutes any non-safe char (anything outside [A-Za-z0-9._-]) with an
    underscore, truncates to 100 chars, strips a leading dot (so the result
    isn't a hidden file), and falls back to 'photo' if the result is empty.
    """
    name = _SAFE_FILENAME_RE.sub("_", raw)
    return name[:100].lstrip(".") or "photo"


def sha256_of_file(path: Path) -> str:
    """Compute SHA-256 hash of file contents in 64KB chunks.

    Returns the lowercase hex digest. Caller is responsible for ensuring
    the file exists and is readable; OSError propagates.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    """Compute SHA-256 hash of an in-memory bytes object.

    Use this for photos parsed in-memory (e.g. PDF-extracted images) that
    never touch disk before hashing. For files on disk, use sha256_of_file.
    """
    return hashlib.sha256(data).hexdigest()

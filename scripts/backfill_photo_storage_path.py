"""Backfill cold_case.case_photo.storage_path from the photos directory.

Walks the photos root, hashes every file (sha256), and sets each
case_photo row's storage_path to the matching file's path relative to the
root. Matching is by content hash — adapter-agnostic, no per-adapter subdir
knowledge needed. A row whose sha256 is not found on disk is left NULL
(its file is missing; restore it by re-ingesting that source).

Idempotent: re-running only updates rows whose storage_path changed.
Run after any cold-case ingestion that adds photos.

Usage:
    DATABASE_URL=... APP_ENV=dev PYTHONPATH=src \\
        .venv/bin/python scripts/backfill_photo_storage_path.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

_PHOTOS_ROOT = Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos")).resolve()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan_disk() -> dict[str, str]:
    """Map sha256 -> path relative to the photos root for every file on disk."""
    by_hash: dict[str, str] = {}
    for path in _PHOTOS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(_PHOTOS_ROOT).as_posix()
        by_hash[_sha256(path)] = rel
    return by_hash


def main() -> int:
    if not _PHOTOS_ROOT.is_dir():
        print(f"photos root does not exist: {_PHOTOS_ROOT}", file=sys.stderr)
        return 1

    by_hash = _scan_disk()
    print(f"scanned {len(by_hash)} distinct photo files under {_PHOTOS_ROOT}")

    engine = create_engine(os.environ["DATABASE_URL"])
    updated = 0
    cleared = 0
    missing = 0
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT case_photo_id, sha256, storage_path FROM cold_case.case_photo")
        ).all()
        for case_photo_id, sha256, current in rows:
            want = by_hash.get(sha256)
            if want is None:
                missing += 1
                continue
            if want != current:
                conn.execute(
                    text(
                        "UPDATE cold_case.case_photo SET storage_path = :p "
                        "WHERE case_photo_id = :id"
                    ),
                    {"p": want, "id": case_photo_id},
                )
                if current is None:
                    updated += 1
                else:
                    cleared += 1

    print(
        f"backfill complete: {updated} newly set, {cleared} corrected, "
        f"{missing} rows with no file on disk (storage_path left as-is)"
    )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

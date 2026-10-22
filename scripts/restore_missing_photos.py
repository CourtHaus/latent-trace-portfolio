"""Restore cold-case photo files missing from data/photos/.

Some states' photo files were lost from the (gitignored) data/photos/ tree
while their cold_case.case_photo DB rows survived. This re-downloads each
photo whose storage_path is NULL from its recorded case_photo.source_url,
writes it under data/photos/<adapter>/<source_case_id>/<filename>, and sets
storage_path + a refreshed sha256.

For DC the source_url is a Summary-of-Case PDF; the victim image is
extracted from it with the cold_case_dc_mpdc PDF parser (the same function
the DC adapter used at ingest time). Direct-image source_urls (UT, MD) are
saved verbatim.

Lighter than a full re-ingest: no detail-page scraping, no transform, no
re-extraction, no case-row churn — it restores only the lost files.

Usage:
    set -a && . ./.env && set +a && export APP_ENV=dev
    PYTHONPATH=src .venv/bin/python scripts/restore_missing_photos.py
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

from casesignal.api.routes.cold_cases import _SOURCE_CODE_TO_PHOTO_DIR
from casesignal.etl.adapters.cold_case_dc_mpdc.pdf_parser import parse_flier
from casesignal.etl.services.polite_http import PoliteHTTPClient

_PHOTOS_ROOT = Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos")).resolve()


def _fetch_image(polite: PoliteHTTPClient, source_url: str) -> tuple[bytes | None, str | None]:
    """Return (image_bytes, content_type) for a photo source_url.

    A PDF source_url (DC Summary-of-Case flier) is parsed and the victim
    image extracted; any other URL is treated as a direct image.
    """
    resp = polite.get(source_url)
    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if source_url.lower().endswith(".pdf") or content_type == "application/pdf":
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(resp.content)
            tmp.flush()
            flier = parse_flier(Path(tmp.name))
        return flier.photo_bytes, flier.photo_content_type
    return resp.content, content_type or None


def main() -> int:
    engine = create_engine(os.environ["DATABASE_URL"])
    polite = PoliteHTTPClient()

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT cp.case_photo_id, cp.filename, cp.source_url,
                       c.source_case_id, ss.source_code
                  FROM cold_case.case_photo cp
                  JOIN cold_case.cases c ON c.case_id = cp.case_id
                  JOIN etl.dataset_version dv ON dv.dataset_version_id = c.dataset_version_id
                  JOIN etl.source_system ss ON ss.source_system_id = dv.source_system_id
                 WHERE cp.storage_path IS NULL AND cp.source_url IS NOT NULL
              ORDER BY ss.source_code, cp.case_photo_id
            """)
        ).all()

    print(f"{len(rows)} photos with no file on disk and a recoverable source_url")
    restored = 0
    failed = 0
    skipped = 0

    for r in rows:
        adapter_dir = _SOURCE_CODE_TO_PHOTO_DIR.get(r.source_code)
        if adapter_dir is None:
            print(f"  SKIP {r.case_photo_id}: unknown source_code {r.source_code!r}")
            skipped += 1
            continue
        try:
            data, content_type = _fetch_image(polite, r.source_url)
        except Exception as exc:  # noqa: BLE001 — a bad fetch must not abort the run
            print(f"  FAIL {r.case_photo_id} {r.source_url}: {exc!r}")
            failed += 1
            continue
        if not data:
            print(f"  FAIL {r.case_photo_id}: no image bytes from {r.source_url}")
            failed += 1
            continue

        rel_path = f"{adapter_dir}/{r.source_case_id}/{r.filename}"
        dest = _PHOTOS_ROOT / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        sha256 = hashlib.sha256(data).hexdigest()

        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE cold_case.case_photo
                       SET storage_path = :path,
                           sha256 = :sha,
                           content_type = COALESCE(:ct, content_type)
                     WHERE case_photo_id = :id
                """),
                {"path": rel_path, "sha": sha256, "ct": content_type, "id": r.case_photo_id},
            )
        restored += 1
        if restored % 50 == 0:
            print(f"  ...{restored} restored")

    if hasattr(polite, "close"):
        polite.close()
    engine.dispose()
    print(f"done: {restored} restored, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
from __future__ import annotations

import argparse
import mimetypes
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from casesignal.storage.photo_storage import build_storage_object_path

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
REJECTED_OBJECT_SEGMENT_CHARS = {"#", ":"}


@dataclass(frozen=True, slots=True)
class PhotoUpload:
    path: Path
    object_name: str
    content_type: str
    source_storage_path: str
    storage_path: str


def sanitize_supabase_storage_path(storage_path: str) -> str:
    """Return a Supabase-safe storage path while preserving normal paths unchanged."""
    sanitized_parts: list[str] = []
    for part in storage_path.strip().strip("/").split("/"):
        if not part:
            continue
        if any(char in part for char in REJECTED_OBJECT_SEGMENT_CHARS):
            cleaned = part.replace("#", " number ").replace(":", " ")
            cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned)
            cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        else:
            cleaned = part

        if not cleaned or cleaned == "..":
            raise ValueError(f"invalid storage path segment after sanitizing: {part!r}")
        sanitized_parts.append(cleaned)

    if not sanitized_parts:
        raise ValueError("invalid empty storage path")
    return "/".join(sanitized_parts)


def iter_photo_uploads(photos_root: Path, *, prefix: str = "") -> list[PhotoUpload]:
    uploads: list[PhotoUpload] = []
    for path in sorted(photos_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(photos_root).as_posix()
        storage_path = sanitize_supabase_storage_path(relative)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        uploads.append(
            PhotoUpload(
                path=path,
                object_name=build_storage_object_path(storage_path, prefix=prefix),
                content_type=content_type,
                source_storage_path=relative,
                storage_path=storage_path,
            )
        )
    return uploads


def storage_path_replacements(uploads: Sequence[PhotoUpload]) -> list[tuple[str, str]]:
    return [
        (upload.source_storage_path, upload.storage_path)
        for upload in uploads
        if upload.source_storage_path != upload.storage_path
    ]


def _encoded_object_name(object_name: str) -> str:
    return "/".join(quote(part, safe="") for part in object_name.split("/"))


def _post_photo_with_retries(
    client: httpx.Client,
    upload: PhotoUpload,
    *,
    base_url: str,
    bucket: str,
    headers_base: dict[str, str],
    max_retries: int,
    retry_sleep_seconds: float,
) -> None:
    url = f"{base_url}/storage/v1/object/{bucket}/{_encoded_object_name(upload.object_name)}"

    for attempt in range(1, max_retries + 1):
        try:
            with upload.path.open("rb") as fh:
                response = client.post(
                    url,
                    headers={**headers_base, "Content-Type": upload.content_type},
                    content=fh.read(),
                )
        except httpx.TransportError:
            if attempt == max_retries:
                raise
        else:
            if response.status_code not in TRANSIENT_STATUS_CODES:
                response.raise_for_status()
                return
            if attempt == max_retries:
                response.raise_for_status()

        if retry_sleep_seconds > 0:
            time.sleep(retry_sleep_seconds * min(2 ** (attempt - 1), 8))


def upload_photos(
    uploads: Sequence[PhotoUpload],
    *,
    supabase_url: str,
    bucket: str,
    service_role_key: str,
    dry_run: bool,
    start_at: int = 1,
    max_retries: int = 4,
    retry_sleep_seconds: float = 1.0,
    transport: httpx.BaseTransport | None = None,
) -> None:
    if start_at < 1:
        raise ValueError("--start-at must be 1 or greater")
    if max_retries < 1:
        raise ValueError("--max-retries must be 1 or greater")

    base_url = supabase_url.rstrip("/")
    headers_base = {
        "Authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
        "x-upsert": "true",
        "Cache-Control": "31536000",
    }

    with httpx.Client(transport=transport, timeout=60.0) as client:
        for index, upload in enumerate(uploads[start_at - 1 :], start=start_at):
            print(f"[{index}/{len(uploads)}] {upload.object_name}")
            if dry_run:
                continue

            _post_photo_with_retries(
                client,
                upload,
                base_url=base_url,
                bucket=bucket,
                headers_base=headers_base,
                max_retries=max_retries,
                retry_sleep_seconds=retry_sleep_seconds,
            )


def update_database_storage_paths(
    replacements: Sequence[tuple[str, str]],
    *,
    database_url: str,
) -> None:
    if not replacements:
        return

    engine = create_engine(database_url, poolclass=NullPool)
    with engine.begin() as conn:
        for old_path, new_path in replacements:
            old_count = conn.execute(
                text("select count(*) from cold_case.case_photo where storage_path = :path"),
                {"path": old_path},
            ).scalar_one()
            new_count = conn.execute(
                text("select count(*) from cold_case.case_photo where storage_path = :path"),
                {"path": new_path},
            ).scalar_one()

            if old_count == 1:
                result = conn.execute(
                    text("""
                        update cold_case.case_photo
                           set storage_path = :new_path
                         where storage_path = :old_path
                        """),
                    {"old_path": old_path, "new_path": new_path},
                )
                if result.rowcount != 1:
                    raise RuntimeError(f"expected one row update for {old_path}")
                print(f"Updated storage_path: {old_path} -> {new_path}")
            elif old_count == 0 and new_count >= 1:
                print(f"Storage path already updated: {new_path}")
            else:
                raise RuntimeError(
                    f"unexpected row counts for {old_path}: old={old_count}, new={new_count}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload local CaseSignal photo files to Supabase Storage."
    )
    parser.add_argument(
        "--photos-root",
        type=Path,
        default=Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos")),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--start-at",
        type=int,
        default=int(os.getenv("SUPABASE_STORAGE_UPLOAD_START_AT", "1")),
        help="Resume at this 1-based upload index.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=int(os.getenv("SUPABASE_STORAGE_UPLOAD_MAX_RETRIES", "4")),
    )
    parser.add_argument(
        "--skip-db-storage-path-updates",
        action="store_true",
        help="Do not update cold_case.case_photo.storage_path for sanitized object names.",
    )
    args = parser.parse_args()

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    prefix = os.getenv("SUPABASE_STORAGE_PREFIX", "").strip()

    if not supabase_url or not bucket or not service_role_key:
        raise SystemExit(
            "SUPABASE_URL, SUPABASE_STORAGE_BUCKET, and SUPABASE_SERVICE_ROLE_KEY are required."
        )

    photos_root = args.photos_root.resolve()
    if not photos_root.is_dir():
        raise SystemExit(f"photos root does not exist: {photos_root}")

    uploads = iter_photo_uploads(photos_root, prefix=prefix)
    replacements = storage_path_replacements(uploads)
    print(f"Uploading {len(uploads)} files from {photos_root} to bucket {bucket}.")
    if replacements:
        print(f"Sanitized {len(replacements)} storage paths rejected by Supabase object keys:")
        for old_path, new_path in replacements:
            print(f"  {old_path} -> {new_path}")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if (
        replacements
        and not args.dry_run
        and not args.skip_db_storage_path_updates
        and not database_url
    ):
        raise SystemExit(
            "DATABASE_URL is required to update case_photo.storage_path for sanitized photo keys. "
            "Set DATABASE_URL or pass --skip-db-storage-path-updates."
        )

    upload_photos(
        uploads,
        supabase_url=supabase_url,
        bucket=bucket,
        service_role_key=service_role_key,
        dry_run=args.dry_run,
        start_at=args.start_at,
        max_retries=args.max_retries,
    )

    if replacements and not args.dry_run and not args.skip_db_storage_path_updates:
        update_database_storage_paths(replacements, database_url=database_url)


if __name__ == "__main__":
    main()

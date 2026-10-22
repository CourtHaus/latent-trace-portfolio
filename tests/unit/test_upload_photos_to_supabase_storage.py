from __future__ import annotations

from pathlib import Path

import httpx

from scripts.upload_photos_to_supabase_storage import (
    PhotoUpload,
    iter_photo_uploads,
    storage_path_replacements,
    upload_photos,
)


def test_iter_photo_uploads_uses_relative_posix_object_names(tmp_path: Path) -> None:
    photos_root = tmp_path / "photos"
    target = photos_root / "cold_case_va" / "123" / "portrait.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"jpg")

    uploads = list(iter_photo_uploads(photos_root, prefix="preview/photos"))

    assert len(uploads) == 1
    assert uploads[0].path == target
    assert uploads[0].object_name == "preview/photos/cold_case_va/123/portrait.jpg"
    assert uploads[0].content_type == "image/jpeg"


def test_iter_photo_uploads_sanitizes_rejected_supabase_object_segments(
    tmp_path: Path,
) -> None:
    photos_root = tmp_path / "photos"
    source_storage_path = (
        "cold_case_ut/SO#: CO1991-107089 AND UPD#: 2015-101175-george-ira-spor/photo_1.jpg"
    )
    target = photos_root / source_storage_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"jpg")

    uploads = iter_photo_uploads(photos_root, prefix="preview")

    expected_storage_path = (
        "cold_case_ut/"
        "SO-number-CO1991-107089-AND-UPD-number-2015-101175-george-ira-spor/"
        "photo_1.jpg"
    )
    assert len(uploads) == 1
    assert uploads[0].source_storage_path == source_storage_path
    assert uploads[0].storage_path == expected_storage_path
    assert uploads[0].object_name == f"preview/{expected_storage_path}"
    assert storage_path_replacements(uploads) == [(source_storage_path, expected_storage_path)]


def test_upload_photos_retries_transient_storage_failures(tmp_path: Path) -> None:
    target = tmp_path / "photo.jpg"
    target.write_bytes(b"jpg")
    upload = PhotoUpload(
        path=target,
        object_name="cold_case_ut/example/photo.jpg",
        content_type="image/jpeg",
        source_storage_path="cold_case_ut/example/photo.jpg",
        storage_path="cold_case_ut/example/photo.jpg",
    )
    status_codes = [504, 200]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_codes.pop(0))

    upload_photos(
        [upload],
        supabase_url="https://example.supabase.co",
        bucket="case-photos",
        service_role_key="service-role-token",
        dry_run=False,
        max_retries=2,
        retry_sleep_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    assert len(requests) == 2
    assert requests[0].headers["x-upsert"] == "true"


def test_upload_photos_start_at_skips_prior_uploads(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    uploads = [
        PhotoUpload(
            path=first,
            object_name="cold_case_ut/example/first.jpg",
            content_type="image/jpeg",
            source_storage_path="cold_case_ut/example/first.jpg",
            storage_path="cold_case_ut/example/first.jpg",
        ),
        PhotoUpload(
            path=second,
            object_name="cold_case_ut/example/second.jpg",
            content_type="image/jpeg",
            source_storage_path="cold_case_ut/example/second.jpg",
            storage_path="cold_case_ut/example/second.jpg",
        ),
    ]
    posted_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted_urls.append(str(request.url))
        return httpx.Response(200)

    upload_photos(
        uploads,
        supabase_url="https://example.supabase.co",
        bucket="case-photos",
        service_role_key="service-role-token",
        dry_run=False,
        start_at=2,
        transport=httpx.MockTransport(handler),
    )

    assert posted_urls == [
        "https://example.supabase.co/storage/v1/object/case-photos/"
        "cold_case_ut/example/second.jpg"
    ]

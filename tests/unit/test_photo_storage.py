from __future__ import annotations

import httpx

from casesignal.storage.photo_storage import (
    SupabaseStorageConfig,
    build_storage_object_path,
    fetch_photo_from_supabase,
)


def test_build_storage_object_path_normalizes_prefix() -> None:
    assert (
        build_storage_object_path("cold_case_va/123/photo.jpg", prefix="/preview/photos/")
        == "preview/photos/cold_case_va/123/photo.jpg"
    )


def test_build_storage_object_path_rejects_parent_segments() -> None:
    try:
        build_storage_object_path("../secret.jpg", prefix="preview")
    except ValueError as exc:
        assert "invalid storage path" in str(exc)
    else:
        raise AssertionError("expected parent traversal to be rejected")


def test_fetch_photo_from_public_supabase_bucket() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"image-bytes")

    config = SupabaseStorageConfig(
        supabase_url="https://example.supabase.co",
        bucket="case-photos",
        service_role_key="",
        prefix="preview",
    )

    photo = fetch_photo_from_supabase(
        "cold_case_va/123/photo.jpg",
        content_type="image/jpeg",
        config=config,
        transport=httpx.MockTransport(handler),
    )

    assert photo is not None
    assert photo.content == b"image-bytes"
    assert photo.content_type == "image/jpeg"
    assert str(requests[0].url) == (
        "https://example.supabase.co/storage/v1/object/public/case-photos/"
        "preview/cold_case_va/123/photo.jpg"
    )
    assert "authorization" not in requests[0].headers


def test_fetch_photo_from_private_supabase_bucket_uses_service_role() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"private-image")

    config = SupabaseStorageConfig(
        supabase_url="https://example.supabase.co/",
        bucket="case-photos",
        service_role_key="service-role-token",
        prefix="",
    )

    photo = fetch_photo_from_supabase(
        "cold_case_va/123/photo.jpg",
        content_type="image/jpeg",
        config=config,
        transport=httpx.MockTransport(handler),
    )

    assert photo is not None
    assert photo.content == b"private-image"
    assert str(requests[0].url) == (
        "https://example.supabase.co/storage/v1/object/case-photos/"
        "cold_case_va/123/photo.jpg"
    )
    assert requests[0].headers["authorization"] == "Bearer service-role-token"
    assert requests[0].headers["apikey"] == "service-role-token"


def test_fetch_photo_from_supabase_returns_none_on_404() -> None:
    config = SupabaseStorageConfig(
        supabase_url="https://example.supabase.co",
        bucket="case-photos",
        service_role_key="",
        prefix="preview",
    )

    photo = fetch_photo_from_supabase(
        "cold_case_va/123/missing.jpg",
        content_type="image/jpeg",
        config=config,
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )

    assert photo is None

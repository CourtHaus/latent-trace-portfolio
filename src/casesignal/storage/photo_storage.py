from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

import httpx


@dataclass(frozen=True, slots=True)
class StoredPhoto:
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class SupabaseStorageConfig:
    supabase_url: str
    bucket: str
    service_role_key: str = ""
    prefix: str = ""
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> SupabaseStorageConfig | None:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "").strip()
        if not supabase_url or not bucket:
            return None

        timeout_raw = os.getenv("SUPABASE_STORAGE_TIMEOUT_SECONDS", "15").strip()
        return cls(
            supabase_url=supabase_url,
            bucket=bucket,
            service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
            prefix=os.getenv("SUPABASE_STORAGE_PREFIX", "").strip(),
            timeout_seconds=float(timeout_raw),
        )


def build_storage_object_path(storage_path: str, *, prefix: str = "") -> str:
    path_parts = _clean_path_parts(storage_path)
    prefix_parts = _clean_path_parts(prefix) if prefix else []
    return "/".join([*prefix_parts, *path_parts])


def fetch_photo_from_supabase(
    storage_path: str,
    *,
    content_type: str,
    config: SupabaseStorageConfig | None = None,
    transport: httpx.BaseTransport | None = None,
) -> StoredPhoto | None:
    resolved_config = config or SupabaseStorageConfig.from_env()
    if resolved_config is None:
        return None

    try:
        object_name = build_storage_object_path(storage_path, prefix=resolved_config.prefix)
    except ValueError:
        return None

    encoded_object_name = "/".join(quote(part, safe="") for part in object_name.split("/"))
    base_url = resolved_config.supabase_url.rstrip("/")
    if resolved_config.service_role_key:
        url = f"{base_url}/storage/v1/object/{resolved_config.bucket}/{encoded_object_name}"
        headers = {
            "Authorization": f"Bearer {resolved_config.service_role_key}",
            "apikey": resolved_config.service_role_key,
        }
    else:
        url = f"{base_url}/storage/v1/object/public/{resolved_config.bucket}/{encoded_object_name}"
        headers = {}

    with httpx.Client(transport=transport, timeout=resolved_config.timeout_seconds) as client:
        response = client.get(url, headers=headers)

    if response.status_code == 404:
        return None
    response.raise_for_status()
    return StoredPhoto(content=response.content, content_type=content_type)


def _clean_path_parts(value: str) -> list[str]:
    parts = [part for part in value.strip().strip("/").split("/") if part]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("invalid storage path")
    return parts

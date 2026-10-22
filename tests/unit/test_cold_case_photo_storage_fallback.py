from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from pytest import MonkeyPatch


class _FakeMappings:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def one_or_none(self) -> dict[str, Any] | None:
        return self._row


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._row)


class _FakeSession:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        return _FakeResult(self._row)


def test_photo_endpoint_uses_supabase_storage_when_local_file_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import casesignal.api.routes.cold_cases as cold_cases
    from casesignal.storage.photo_storage import StoredPhoto

    monkeypatch.setattr(cold_cases, "_PHOTOS_ROOT", tmp_path)
    monkeypatch.setattr(
        cold_cases,
        "fetch_photo_from_supabase",
        lambda storage_path, content_type: StoredPhoto(
            content=b"storage-photo",
            content_type=content_type,
        ),
    )

    response = cold_cases.get_cold_case_photo(
        request=Request({"type": "http", "method": "GET", "path": "/"}),
        case_id=123,
        filename="portrait.jpg",
        session=_FakeSession(
            {
                "content_type": "image/jpeg",
                "storage_path": "cold_case_va/123/portrait.jpg",
                "source_code": "cold_case_va_2026_04_21",
                "source_case_id": "123",
            }
        ),
    )

    assert response.body == b"storage-photo"
    assert response.media_type == "image/jpeg"
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"

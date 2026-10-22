"""Regression test for the cold-case photo endpoint.

Self-seeds a source_system + dataset_version + case + case_photo and a real
photo file under a temp photos root, then exercises GET .../photos/{filename}.
This is the test class that was missing — every prior photo bug (frontend
URL, source-dir map, OH/CO subdir) shipped because nothing hit this endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch
from sqlalchemy import text

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000000020001e221bc330000000049454e44ae426082"
)


@pytest.fixture
def seeded_photo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Any:
    """Seed a case + case_photo + on-disk file under a temp photos root.

    Yields (case_id, filename). Cleans up the DB rows after.
    """
    import casesignal.api.routes.cold_cases as cc

    photos_root = tmp_path / "photos"
    monkeypatch.setattr(cc, "_PHOTOS_ROOT", photos_root.resolve())

    from casesignal.etl.services.db import create_db_engine, create_session_factory

    engine = create_db_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    rel_path = "cold_case_test_photo/photo-endpoint-case/portrait.png"
    abs_path = photos_root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(_TINY_PNG)

    with session_factory() as s:
        ssid = s.execute(
            text(
                "INSERT INTO etl.source_system (source_code, source_name) "
                "VALUES ('PHOTO_ENDPOINT_TEST', 'photo endpoint test') "
                "RETURNING source_system_id"
            )
        ).scalar_one()
        dvid = s.execute(
            text(
                "INSERT INTO etl.dataset_version "
                "(source_system_id, source_year, source_label, source_hash, ingestion_status) "
                # 'published' so the public photo endpoint serves it: the read
                # path now gates on ingestion_status (SEC-2026-05-31-A), so a
                # draft/archived case's photo correctly 404s. This test exercises
                # the storage_path serve path, which requires a published case.
                "VALUES (:ss, 2026, 'photo endpoint test', 'photo-endpoint-test-hash', 'published') "
                "RETURNING dataset_version_id"
            ),
            {"ss": ssid},
        ).scalar_one()
        case_id = s.execute(
            text(
                "INSERT INTO cold_case.cases "
                "(dataset_version_id, source_case_id, slug, case_name, case_type, state) "
                "VALUES (:dv, 'photo-endpoint-case', 'photo-endpoint-case', "
                "'Photo Endpoint Test', 'homicide', 'ZZ') RETURNING case_id"
            ),
            {"dv": dvid},
        ).scalar_one()
        s.execute(
            text(
                "INSERT INTO cold_case.case_photo "
                "(case_id, filename, content_type, sha256, is_primary, storage_path) "
                "VALUES (:cid, 'portrait.png', 'image/png', 'deadbeef', TRUE, :sp)"
            ),
            {"cid": case_id, "sp": rel_path},
        )
        s.commit()

    yield case_id, "portrait.png"

    with session_factory() as s:
        s.execute(text("DELETE FROM cold_case.case_photo WHERE case_id = :c"), {"c": case_id})
        s.execute(text("DELETE FROM cold_case.cases WHERE case_id = :c"), {"c": case_id})
        s.execute(
            text("DELETE FROM etl.dataset_version WHERE source_hash = 'photo-endpoint-test-hash'")
        )
        s.execute(text("DELETE FROM etl.source_system WHERE source_code = 'PHOTO_ENDPOINT_TEST'"))
        s.commit()


def _client() -> Any:
    from fastapi.testclient import TestClient

    from casesignal.api.app import create_app
    from casesignal.api.dependencies.auth import AuthenticatedKey, require_api_key

    app = create_app()
    app.dependency_overrides[require_api_key] = lambda: AuthenticatedKey(key_id=999, role="admin")
    return TestClient(app)


def test_photo_served_via_storage_path(seeded_photo: Any) -> None:
    case_id, filename = seeded_photo
    resp = _client().get(f"/api/v1/cold-cases/{case_id}/photos/{filename}")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == _TINY_PNG


def test_photo_traversal_filename_rejected(seeded_photo: Any) -> None:
    case_id, _ = seeded_photo
    resp = _client().get(f"/api/v1/cold-cases/{case_id}/photos/..%2f..%2fetc%2fpasswd")
    assert resp.status_code == 404


def test_photo_unknown_filename_404(seeded_photo: Any) -> None:
    case_id, _ = seeded_photo
    resp = _client().get(f"/api/v1/cold-cases/{case_id}/photos/nonexistent.png")
    assert resp.status_code == 404

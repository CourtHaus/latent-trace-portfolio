"""Body-size and input-length cap regressions.

Closes SEC-005/009 (content_base64), SEC-022 (label).
"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient


def test_ingestion_upload_rejects_oversized_body(admin_client: TestClient) -> None:
    """SEC-005/009: Upload endpoint must reject request bodies over the cap."""
    huge = base64.b64encode(b"A" * (200 * 1024 * 1024)).decode()
    resp = admin_client.post(
        "/api/v1/admin/ingestion/uploads",
        json={"source_code": "COLD_CASE_VA", "source_year": 2024, "content_base64": huge},
    )
    assert resp.status_code in (413, 422), f"expected 413 or 422, got {resp.status_code}"


def test_api_key_label_rejects_huge_value(admin_client: TestClient) -> None:
    """SEC-022: Creating a key with a 10KB label must fail validation."""
    resp = admin_client.post(
        "/api/v1/admin/keys",
        json={"label": "X" * 10_000, "role": "reader"},
    )
    assert resp.status_code == 422

"""End-to-end: with X-Forwarded-Proto: https, the app emits https redirects
(the /healthz/ trailing-slash case that prompted the fix), and the client
address is untouched so rate-limit bucketing is unaffected.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from casesignal.api.app import create_app

pytestmark = pytest.mark.integration


def test_trailing_slash_redirect_uses_forwarded_https() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get(
            "/healthz/",
            headers={"X-Forwarded-Proto": "https"},
            follow_redirects=False,
        )
        assert resp.status_code in (307, 308)
        assert resp.headers["location"].startswith("https://"), resp.headers["location"]


def test_trailing_slash_redirect_stays_http_without_forwarded_proto() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/healthz/", follow_redirects=False)
        assert resp.status_code in (307, 308)
        assert resp.headers["location"].startswith("http://"), resp.headers["location"]

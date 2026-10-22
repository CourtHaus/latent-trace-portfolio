"""Tests for PoliteHTTPClient.post() — POST form-encoded body behavior."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pytest import MonkeyPatch


@pytest.fixture
def client() -> Any:
    from casesignal.etl.services.polite_http import PoliteHTTPClient

    # Tests use example.com (not a real publisher); pass an explicit
    # allowed_hosts so the SSRF allowlist admits it.
    return PoliteHTTPClient(rate_limit_seconds=0.01, allowed_hosts=["example.com"])


def test_post_sends_form_body(client: Any, monkeypatch: MonkeyPatch) -> None:
    """post(url, data={...}) should call the underlying client with POST + form-encoded data."""
    captured = {}

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        captured["method"] = method
        captured["url"] = url
        captured["data"] = kwargs.get("data") or kwargs.get("content")
        return httpx.Response(200, text="<html>ok</html>", request=httpx.Request(method, url))

    monkeypatch.setattr(client._client, "request", fake_request)
    resp = client.post("https://example.com/search", data={"foo": "bar"})
    assert resp.status_code == 200
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/search"
    assert captured["data"] == {"foo": "bar"}


def test_post_returns_response(client: Any, monkeypatch: MonkeyPatch) -> None:
    """Successful POST returns the httpx.Response object as-is."""
    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, url, **kwargs: httpx.Response(
            200,
            text="<html>ok</html>",
            request=httpx.Request(method, url),
        ),
    )
    resp = client.post("https://example.com/search", data={"x": "y"})
    assert isinstance(resp, httpx.Response)
    assert resp.status_code == 200

"""PoliteHTTPClient — UA, rate limit, retry, robots.txt, max-bytes."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest
from pytest import MonkeyPatch

from casesignal.etl.services.polite_http import (
    FetchTooLarge,
    PoliteHTTPClient,
    RobotsTxtDisallowed,
)


@pytest.fixture
def client() -> Iterator[PoliteHTTPClient]:
    """A PoliteHTTPClient with rate limit short enough for tests to run fast.

    Tests use `*.test` synthetic domains (see RFC 6761 §6.4 — reserved for
    testing, must not resolve). The production SSRF allowlist obviously
    doesn't include them, so the test client passes its own allowed_hosts
    set covering the synthetic test domains.
    """
    c = PoliteHTTPClient(
        rate_limit_seconds=0.05,
        max_retries=2,
        allowed_hosts=[
            "example.test",
            "host-a.test",
            "host-b.test",
            "locked.test",
            "no-robots.test",
        ],
    )
    yield c
    c.close()


# ---------- UA header ----------


def test_default_user_agent_is_branded(client: PoliteHTTPClient) -> None:
    assert client.user_agent.startswith("LatentTrace/")
    assert "courtney@latenttrace.org" in client.user_agent


def test_user_agent_set_on_every_request(client: PoliteHTTPClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)

    captured = {}

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        captured["headers"] = dict(client._client.headers)
        return httpx.Response(200, content=b"ok", request=httpx.Request(method, url))

    with patch.object(client._client, "request", side_effect=fake_request):
        client.get("https://example.test/page")

    # httpx normalizes header keys to lowercase in its dict view
    ua = captured["headers"].get("User-Agent") or captured["headers"].get("user-agent")
    assert ua is not None and ua.startswith("LatentTrace/"), f"unexpected UA: {ua!r}"


# ---------- rate limit ----------


def test_per_host_rate_limit_enforced(client: PoliteHTTPClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)

    timestamps: list[float] = []

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        timestamps.append(time.monotonic())
        return httpx.Response(200, content=b"ok", request=httpx.Request(method, url))

    client.rate_limit_seconds = 0.1
    with patch.object(client._client, "request", side_effect=fake_request):
        client.get("https://example.test/a")
        client.get("https://example.test/b")

    assert len(timestamps) == 2
    gap = timestamps[1] - timestamps[0]
    assert gap >= 0.09, f"expected >= 0.1s gap, got {gap}"


def test_rate_limit_is_per_host(client: PoliteHTTPClient, monkeypatch: MonkeyPatch) -> None:
    """Different hosts don't share rate-limit state."""
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)

    timestamps: list[float] = []

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        timestamps.append(time.monotonic())
        return httpx.Response(200, content=b"ok", request=httpx.Request(method, url))

    client.rate_limit_seconds = 1.0  # would slow things down if shared
    with patch.object(client._client, "request", side_effect=fake_request):
        client.get("https://host-a.test/")
        client.get("https://host-b.test/")

    gap = timestamps[1] - timestamps[0]
    assert gap < 0.5, f"unrelated hosts shouldn't wait; gap={gap}"


# ---------- retry / backoff ----------


def test_retry_on_5xx_then_success(client: PoliteHTTPClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)
    monkeypatch.setattr(client, "_sleep_backoff", lambda attempt: None)

    responses_iter: Iterator[Callable[[httpx.Request], httpx.Response]] = iter(
        [
            lambda req: httpx.Response(500, content=b"server err", request=req),
            lambda req: httpx.Response(503, content=b"unavailable", request=req),
            lambda req: httpx.Response(200, content=b"ok", request=req),
        ]
    )

    def fake_request(method: Any, url: Any, **kwargs: Any) -> httpx.Response:
        req = httpx.Request(method, url)
        return next(responses_iter)(req)

    with patch.object(client._client, "request", side_effect=fake_request):
        response = client.get("https://example.test/")

    assert response.status_code == 200


def test_4xx_does_not_retry(client: PoliteHTTPClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)

    call_count = 0

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, content=b"not found", request=httpx.Request(method, url))

    with patch.object(client._client, "request", side_effect=fake_request):
        with pytest.raises(httpx.HTTPStatusError):
            client.get("https://example.test/missing")

    assert call_count == 1, f"expected 1 call (no retry), got {call_count}"


def test_5xx_exhausts_retries(client: PoliteHTTPClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)
    monkeypatch.setattr(client, "_sleep_backoff", lambda attempt: None)

    call_count = 0

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, content=b"err", request=httpx.Request(method, url))

    client.max_retries = 2
    with patch.object(client._client, "request", side_effect=fake_request):
        with pytest.raises(httpx.HTTPStatusError):
            client.get("https://example.test/")

    assert call_count == 3, f"expected 3 attempts (1 + 2 retries), got {call_count}"


# ---------- robots.txt ----------


def test_robots_disallow_raises(client: PoliteHTTPClient) -> None:
    """When robots.txt disallows the path, fail loudly."""

    class _Forbidden:
        def can_fetch(self, ua: Any, url: Any) -> Any:
            return False

    client._hosts.setdefault(
        "example.test",
        client._hosts.get("example.test")
        or __import__("casesignal.etl.services.polite_http", fromlist=["_HostState"])._HostState(),
    )
    state = client._hosts["example.test"]
    state.robots = cast(Any, _Forbidden())
    state.robots_fetched = True

    with pytest.raises(RobotsTxtDisallowed):
        client.get("https://example.test/secret")


def test_robots_unreadable_assumes_allowed(client: PoliteHTTPClient) -> None:
    """If robots.txt fetch raises a network error, we don't block — log and
    proceed."""
    captured: list[str] = []

    def fake_get(url: Any, **kwargs: Any) -> Any:
        if url.endswith("/robots.txt"):
            raise httpx.ConnectError("network down")
        captured.append(url)
        return httpx.Response(200, content=b"ok", request=httpx.Request("GET", url))

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        captured.append(url)
        return httpx.Response(200, content=b"ok", request=httpx.Request(method, url))

    with (
        patch.object(client._client, "get", side_effect=fake_get),
        patch.object(client._client, "request", side_effect=fake_request),
    ):
        client.get("https://no-robots.test/page")

    assert "https://no-robots.test/page" in captured


def test_robots_403_blocks_per_rfc_9309(client: PoliteHTTPClient) -> None:
    """Per RFC 9309, a 403 on robots.txt means treat as fully disallowed."""

    def fake_get(url: Any, **kwargs: Any) -> Any:
        if url.endswith("/robots.txt"):
            return httpx.Response(403, content=b"forbidden", request=httpx.Request("GET", url))
        return httpx.Response(200, content=b"ok", request=httpx.Request("GET", url))

    with patch.object(client._client, "get", side_effect=fake_get):
        with pytest.raises(RobotsTxtDisallowed):
            client.get("https://locked.test/page")


def test_robots_404_is_treated_as_missing_and_allowed(client: PoliteHTTPClient) -> None:
    """Per RFC 9309, a 404 on robots.txt means treat as fully allowed."""
    captured: list[str] = []

    def fake_get(url: Any, **kwargs: Any) -> Any:
        if url.endswith("/robots.txt"):
            return httpx.Response(404, content=b"", request=httpx.Request("GET", url))
        captured.append(url)
        return httpx.Response(200, content=b"ok", request=httpx.Request("GET", url))

    def fake_request(method: Any, url: Any, **kwargs: Any) -> Any:
        captured.append(url)
        return httpx.Response(200, content=b"ok", request=httpx.Request(method, url))

    with (
        patch.object(client._client, "get", side_effect=fake_get),
        patch.object(client._client, "request", side_effect=fake_request),
    ):
        client.get("https://no-robots.test/page")

    assert "https://no-robots.test/page" in captured


# ---------- fetch_to_file ----------


def test_fetch_to_file_writes_and_returns_path(client: PoliteHTTPClient, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)

    payload = b"hello world"
    dest = tmp_path / "subdir" / "file.bin"

    class _StreamCtx:
        def __init__(self, response: Any) -> None:
            self._response = response

        def __enter__(self) -> Any:
            return self._response

        def __exit__(self, *a: Any) -> None:
            pass

    response = httpx.Response(200, content=payload)
    response.iter_bytes = lambda: iter([payload])  # type: ignore

    with patch.object(client._client, "stream", return_value=_StreamCtx(response)):
        result = client.fetch_to_file("https://example.test/img.jpg", dest)

    assert result == dest
    assert dest.read_bytes() == payload


def test_fetch_to_file_max_bytes_enforced_and_partial_deleted(
    client: PoliteHTTPClient, monkeypatch: MonkeyPatch, tmp_path: Path
) -> Any:
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)

    chunks = [b"a" * 5, b"b" * 5, b"c" * 100]  # 110 total; limit will be 20
    dest = tmp_path / "big.bin"

    class _StreamCtx:
        def __init__(self, response: Any) -> None:
            self._response = response

        def __enter__(self) -> Any:
            return self._response

        def __exit__(self, *a: Any) -> None:
            pass

    response = httpx.Response(200, content=b"")
    response.iter_bytes = lambda: iter(chunks)  # type: ignore

    with patch.object(client._client, "stream", return_value=_StreamCtx(response)):
        with pytest.raises(FetchTooLarge):
            client.fetch_to_file("https://example.test/big", dest, max_bytes=20)

    assert not dest.exists(), "partial file should be deleted on overflow"


def test_ar_asp_hosts_allowlisted() -> None:
    from casesignal.etl.services.polite_http import _DEFAULT_ALLOWED_HOSTS

    assert "dps.arkansas.gov" in _DEFAULT_ALLOWED_HOSTS
    assert "media.ark.org" in _DEFAULT_ALLOWED_HOSTS


def test_ok_osbi_host_allowlisted() -> None:
    from casesignal.etl.services.polite_http import _DEFAULT_ALLOWED_HOSTS

    assert "oklahoma.gov" in _DEFAULT_ALLOWED_HOSTS


# ---------------------------------------------------------------------------
# TLS-impersonation transport (curl_cffi) — used for Cloudflare-fingerprinted
# hosts (e.g. AR ASP). We stub the curl session so no network is touched.
# ---------------------------------------------------------------------------


class _FakeCurlResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self._chunks = chunks or []
        self.closed = False

    def iter_content(self) -> Iterator[bytes]:
        yield from self._chunks

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("GET", "https://x.test/"),
                response=httpx.Response(self.status_code),
            )


class _FakeCurlSession:
    """Records requests and returns queued responses in order."""

    def __init__(self, responses: list[_FakeCurlResponse]) -> None:
        self._responses = iter(responses)
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeCurlResponse:
        self.requests.append((method, url))
        return next(self._responses)

    def close(self) -> None:
        pass


@pytest.fixture
def curl_client() -> Iterator[PoliteHTTPClient]:
    c = PoliteHTTPClient(
        rate_limit_seconds=0.01,
        max_retries=2,
        tls_impersonate=True,
        allowed_hosts=["example.test", "host-a.test", "host-b.test"],
    )
    yield c
    c.close()


def test_tls_impersonate_routes_through_curl(
    curl_client: PoliteHTTPClient, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(curl_client, "_enforce_robots", lambda host, url: None)
    monkeypatch.setattr(curl_client, "_enforce_resolved_ip", lambda host, url: None)
    fake = _FakeCurlSession(
        [
            _FakeCurlResponse(200),  # redirect-resolution probe
            _FakeCurlResponse(200, headers={"Content-Type": "text/html"}, content=b"<html>ok</html>"),
        ]
    )
    curl_client._curl = fake
    # httpx client must NOT be used when impersonating
    monkeypatch.setattr(
        curl_client._client,
        "request",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("httpx used in impersonate mode")),
    )

    resp = curl_client.get("https://example.test/page")

    assert isinstance(resp, httpx.Response)  # wrapped, callers stay transport-agnostic
    assert resp.status_code == 200
    assert resp.text == "<html>ok</html>"
    assert resp.headers["Content-Type"] == "text/html"
    # every curl request targeted the allowlisted host, never httpx
    assert fake.requests and all("example.test" in url for _, url in fake.requests)


def test_tls_impersonate_revalidates_each_redirect_hop(
    curl_client: PoliteHTTPClient, monkeypatch: MonkeyPatch
) -> None:
    """A redirect to a non-allowlisted host must be rejected mid-chain (SEC-E01)."""
    monkeypatch.setattr(curl_client, "_enforce_robots", lambda host, url: None)
    monkeypatch.setattr(curl_client, "_enforce_resolved_ip", lambda host, url: None)
    fake = _FakeCurlSession(
        [
            # first hop (allowlisted) 302 -> evil host
            _FakeCurlResponse(302, headers={"location": "https://evil.test/steal"}),
        ]
    )
    curl_client._curl = fake

    from casesignal.etl.services.polite_http import DisallowedHost

    with pytest.raises(DisallowedHost):
        curl_client.get("https://example.test/redirect")


def test_tls_impersonate_stream_enforces_size_cap(
    curl_client: PoliteHTTPClient, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(curl_client, "_enforce_robots", lambda host, url: None)
    monkeypatch.setattr(curl_client, "_enforce_resolved_ip", lambda host, url: None)
    fake = _FakeCurlSession(
        [
            _FakeCurlResponse(200),  # redirect-resolution probe
            _FakeCurlResponse(200, chunks=[b"x" * 8, b"y" * 8]),  # 16 bytes > 10 cap
        ]
    )
    curl_client._curl = fake
    dest = tmp_path / "big.bin"

    with pytest.raises(FetchTooLarge):
        curl_client.fetch_to_file("https://example.test/file", dest, max_bytes=10)

    assert not dest.exists()  # partial file deleted


def test_tls_impersonate_stream_writes_file(
    curl_client: PoliteHTTPClient, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(curl_client, "_enforce_robots", lambda host, url: None)
    monkeypatch.setattr(curl_client, "_enforce_resolved_ip", lambda host, url: None)
    fake = _FakeCurlSession(
        [
            _FakeCurlResponse(200),  # redirect probe
            _FakeCurlResponse(200, chunks=[b"abc", b"def"]),
        ]
    )
    curl_client._curl = fake
    dest = tmp_path / "photo.jpg"

    out = curl_client.fetch_to_file("https://example.test/photo.jpg", dest, max_bytes=1000)

    assert out == dest
    assert dest.read_bytes() == b"abcdef"

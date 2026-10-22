"""Client-IP derivation for rate-limit bucketing (SEC-B02).

Behind a reverse proxy the immediate TCP peer is the proxy, not the client,
so per-IP rate buckets collapse to one shared bucket unless we read
X-Forwarded-For. But trusting X-Forwarded-For naively lets a client spoof the
leftmost entry to evade or frame a bucket. The trusted-hop approach counts in
from the right: each trusted proxy appends the IP it received from, so the IP
appended by the OUTERMOST trusted proxy (= the real client) sits at index
-hops. Anything the client prepends is ignored.

RATE_LIMIT_TRUSTED_PROXY_HOPS defaults to 0 (trust nothing → use the peer IP),
preserving the pre-fix behavior with zero deploy regression.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from casesignal.api.middleware.rate_limit import _client_ip


def _make_request(headers: dict[str, str], peer: str = "10.0.0.1") -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 12345),
    }
    return Request(scope)


def test_hops_zero_ignores_forwarded_for_and_uses_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", raising=False)
    req = _make_request({"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}, peer="10.0.0.1")
    assert _client_ip(req) == "10.0.0.1"


def test_one_hop_takes_ip_appended_by_trusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    # Client sent "1.1.1.1" (spoofed); the single trusted proxy appended the
    # real client IP 9.9.9.9 as the last entry.
    req = _make_request({"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})
    assert _client_ip(req) == "9.9.9.9"


def test_two_hops_counts_in_from_the_right(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "2")
    # client(real)=9.9.9.9 → LB appended it, frontend appended LB's 10.0.0.5
    req = _make_request({"X-Forwarded-For": "1.1.1.1, 9.9.9.9, 10.0.0.5"})
    assert _client_ip(req) == "9.9.9.9"


def test_spoofed_prefix_cannot_change_the_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    a = _make_request({"X-Forwarded-For": "203.0.113.7, 9.9.9.9"})
    b = _make_request({"X-Forwarded-For": "198.51.100.250, 9.9.9.9"})
    # Same real client, different spoofed prefixes → must resolve to one IP.
    assert _client_ip(a) == _client_ip(b) == "9.9.9.9"


def test_hops_set_but_no_forwarded_for_falls_back_to_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    req = _make_request({}, peer="10.0.0.1")
    assert _client_ip(req) == "10.0.0.1"


def test_chain_shorter_than_hops_falls_back_to_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "3")
    req = _make_request({"X-Forwarded-For": "9.9.9.9"}, peer="10.0.0.1")
    # Fewer entries than trusted hops means the header is not trustworthy.
    assert _client_ip(req) == "10.0.0.1"


def test_garbage_hops_value_defaults_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "not-a-number")
    req = _make_request({"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}, peer="10.0.0.1")
    assert _client_ip(req) == "10.0.0.1"


def test_non_ip_at_trusted_position_falls_back_to_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    req = _make_request({"X-Forwarded-For": "1.1.1.1, garbage"}, peer="10.0.0.1")
    assert _client_ip(req) == "10.0.0.1"

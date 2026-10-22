"""SSRF defense: PoliteHTTPClient host allowlist + IP-literal denylist.

These tests exercise the _enforce_host_allowlist hook directly. The hook
runs before robots.txt enforcement and before any network call, so we can
test it against a wide range of malicious URL shapes without standing up
a server or mocking httpx.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from casesignal.etl.services.polite_http import DisallowedHost, PoliteHTTPClient

# --- Static allowlist ---


def test_default_allowlist_admits_known_publisher_hosts() -> None:
    """The default allowlist includes every host from src/casesignal/etl/sources/*.yaml."""
    client = PoliteHTTPClient()
    for host in (
        "www.baltimorecountymd.gov",
        "www.aacounty.org",
        "www.howardcountymd.gov",
        "harfordsheriff.org",
        "www.ccso.us",
        "www.wicomicosheriff.com",
        "mpdc.dc.gov",
        "apps.colorado.gov",
        "bci.utah.gov",
        "www.ohioattorneygeneral.gov",
        "www.doj.nh.gov",
    ):
        # No exception → host is allowed
        client._enforce_host_allowlist(host, f"https://{host}/some/path")


def test_disallowed_hostname_rejected() -> None:
    client = PoliteHTTPClient()
    for bad in (
        "evil.example.com",
        "attacker.com",
        "google.com",  # legitimate but not a publisher we ingest from
        "127.0.0.1.nip.io",  # rebinding-style hostname
    ):
        with pytest.raises(DisallowedHost, match="non-allowlisted host"):
            client._enforce_host_allowlist(bad, f"https://{bad}/x")


def test_constructor_arg_overrides_defaults() -> None:
    """Passing allowed_hosts replaces the default set entirely."""
    client = PoliteHTTPClient(allowed_hosts=["test.example.com"])
    client._enforce_host_allowlist("test.example.com", "https://test.example.com/x")
    # The default publisher hosts are no longer admitted
    with pytest.raises(DisallowedHost):
        client._enforce_host_allowlist("mpdc.dc.gov", "https://mpdc.dc.gov/x")


def test_env_extra_hosts_extend_defaults() -> None:
    """CASESIGNAL_HTTP_EXTRA_HOSTS adds to the defaults (additive, not override)."""
    with patch.dict(os.environ, {"CASESIGNAL_HTTP_EXTRA_HOSTS": "a.test,b.test"}):
        client = PoliteHTTPClient()
        # New hosts admitted
        client._enforce_host_allowlist("a.test", "https://a.test/x")
        client._enforce_host_allowlist("b.test", "https://b.test/y")
        # Defaults still admitted
        client._enforce_host_allowlist("mpdc.dc.gov", "https://mpdc.dc.gov/z")


# --- IP-literal denylist ---


def test_loopback_ip_literal_rejected() -> None:
    client = PoliteHTTPClient(allowed_hosts=["any.test"])
    for url in (
        "http://127.0.0.1/x",
        "http://127.1.2.3/x",  # also loopback per RFC
        "http://[::1]/x",  # IPv6 loopback
    ):
        with pytest.raises(DisallowedHost, match="private/reserved range"):
            # Parse host the same way polite_http does
            from urllib.parse import urlparse

            host = urlparse(url).hostname or ""
            client._enforce_host_allowlist(host, url)


def test_link_local_ip_literal_rejected() -> None:
    """The headline SSRF case: AWS metadata service at 169.254.169.254."""
    client = PoliteHTTPClient(allowed_hosts=["any.test"])
    with pytest.raises(DisallowedHost, match="private/reserved range"):
        client._enforce_host_allowlist(
            "169.254.169.254", "http://169.254.169.254/latest/meta-data/"
        )


def test_private_ip_literal_rejected() -> None:
    client = PoliteHTTPClient(allowed_hosts=["any.test"])
    for ip in ("10.0.0.1", "10.255.255.1", "172.16.0.1", "172.31.255.1", "192.168.1.1"):
        with pytest.raises(DisallowedHost, match="private/reserved range"):
            client._enforce_host_allowlist(ip, f"http://{ip}/x")


def test_public_ip_literal_rejected() -> None:
    """Even public IPs are refused; we always go through hostnames."""
    client = PoliteHTTPClient(allowed_hosts=["any.test"])
    with pytest.raises(DisallowedHost, match="bare-IP URLs"):
        client._enforce_host_allowlist("8.8.8.8", "http://8.8.8.8/x")


def test_empty_host_rejected() -> None:
    client = PoliteHTTPClient()
    with pytest.raises(DisallowedHost, match="missing host"):
        client._enforce_host_allowlist("", "not-a-url")


# --- End-to-end: get() raises ---


def test_get_raises_disallowed_host_before_any_network_call() -> None:
    """polite.get() of a non-allowlisted host raises DisallowedHost without
    any DNS / TCP. Verified by the absence of a real server at evil.example.com."""
    client = PoliteHTTPClient()
    with pytest.raises(DisallowedHost):
        client.get("https://evil.example.com/payload")


def test_get_raises_disallowed_host_on_metadata_url() -> None:
    """The SSRF headline case: blocked before any request leaves the host."""
    client = PoliteHTTPClient()
    with pytest.raises(DisallowedHost, match="private/reserved range"):
        client.get("http://169.254.169.254/latest/meta-data/iam/security-credentials/")


# --- DNS-rebinding guard (SEC-E01) ---


def test_resolved_private_ip_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An allowlisted hostname that resolves to a private/reserved IP is rejected."""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 0))],
    )
    client = PoliteHTTPClient(allowed_hosts=["rebind.test"])
    with pytest.raises(DisallowedHost, match="DNS rebinding"):
        client._enforce_resolved_ip("rebind.test", "https://rebind.test/x")


def test_resolved_public_ip_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 0))]
    )
    client = PoliteHTTPClient(allowed_hosts=["ok.test"])
    # No exception → public resolution is allowed.
    client._enforce_resolved_ip("ok.test", "https://ok.test/x")


def test_resolution_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient DNS errors must not break scraping — fail open."""
    import socket

    def boom(*a: object, **k: object) -> object:
        raise OSError("temporary resolution failure")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    client = PoliteHTTPClient(allowed_hosts=["flaky.test"])
    client._enforce_resolved_ip("flaky.test", "https://flaky.test/x")  # no raise


# --- Redirect hops are re-checked (SEC-E01) ---


def test_request_hook_is_registered_on_the_client() -> None:
    client = PoliteHTTPClient(allowed_hosts=["ok.test"])
    assert client._validate_request_url in client._client.event_hooks["request"]


def test_redirect_to_internal_host_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 302 from an allowlisted host to an internal address is blocked on the
    redirect hop by the request event hook — the metadata request never lands."""
    import socket

    import httpx

    # Fail-open the resolve guard for the (synthetic) initial host.
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )

    client = PoliteHTTPClient(allowed_hosts=["example.test"])
    monkeypatch.setattr(client, "_enforce_robots", lambda host, url: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.test":
            return httpx.Response(
                302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200, content=b"SHOULD-NOT-REACH-INTERNAL")

    client._client = httpx.Client(
        follow_redirects=True,
        event_hooks={"request": [client._validate_request_url]},
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(DisallowedHost, match="private/reserved range"):
            client.get("https://example.test/start")
    finally:
        client.close()

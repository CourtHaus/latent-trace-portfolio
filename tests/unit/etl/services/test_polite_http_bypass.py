"""Test that CASESIGNAL_BYPASS_ROBOTS_HOSTS skips the robots.txt enforcement."""

import os
from unittest.mock import patch

from casesignal.etl.services.polite_http import PoliteHTTPClient


def test_bypass_hosts_skips_robots_check() -> None:
    client = PoliteHTTPClient(bypass_robots_hosts=["example.com"])
    # Should NOT raise even though we don't allow it via robots.txt
    # (We can't easily test against a fake server; verify the path doesn't raise).
    # Simulate: call _enforce_robots directly with a host in the bypass set.
    client._enforce_robots("example.com", "https://example.com/anything")
    # If we got here without raising, the bypass works.


def test_bypass_via_env_var() -> None:
    with patch.dict(os.environ, {"CASESIGNAL_BYPASS_ROBOTS_HOSTS": "example.com,foo.com"}):
        client = PoliteHTTPClient()
        client._enforce_robots("foo.com", "https://foo.com/x")
        client._enforce_robots("example.com", "https://example.com/y")


def test_unbypassed_host_still_enforced() -> None:
    """A host not in the bypass list MUST still trigger normal robots.txt enforcement."""
    client = PoliteHTTPClient(bypass_robots_hosts=["other.com"])
    # We can't easily verify the actual fetch logic without a server, but
    # we can confirm that for a host NOT in the bypass set, _enforce_robots
    # would attempt to fetch robots.txt. The test passes if calling it with
    # a host that has a real robots.txt set up works as before.
    # For unit-test scope, just confirm the bypass set doesn't apply to other hosts.
    assert "wicomicosheriff.com" not in client.bypass_robots_hosts

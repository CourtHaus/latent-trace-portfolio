"""Polite HTTP client for scraping public-sector cold-case sources.

Centralizes the rules we follow when scraping:
- Identify ourselves honestly via a CaseSignal-branded User-Agent (no
  Firefox-style fallback that misrepresents identity).
- Respect robots.txt — fetch once per host and cache.
- Per-host rate limiting (default 2.0 seconds between requests).
- Exponential backoff retry (1s, 2s, 4s, 8s) on 5xx and connection errors.
- 4xx is non-retryable and raises immediately.
- Configurable timeout (default 30 seconds).
- fetch_to_file streams bytes to disk with a max-bytes ceiling
  (default 25 MB) — aborts and deletes the partial file if exceeded.

Used by HTML-scrape adapters (Phase 1: cold_case_md_baltimore_county).
Not used by the FastAPI app or by the geocoding worker; those have their
own HTTP needs (Census API, etc.) without polite-scraping requirements.

Robots.txt bypass
-----------------
Some public-records sites publish a blanket ``User-Agent: * / Disallow: /``
that blocks all bots, even though the records are freely accessible via a
browser.  Set ``CASESIGNAL_BYPASS_ROBOTS_HOSTS`` (comma-separated hostnames)
to skip the robots.txt check for those specific hosts.  A WARNING is logged
once per host so the bypass is always visible in the run log.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
import urllib.robotparser
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)


_DEFAULT_USER_AGENT = (
    "LatentTrace/0.1 (cold-case research; " "contact: courtney@latenttrace.org)"
)
_DEFAULT_RATE_LIMIT_SECONDS = 2.0
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 4
_DEFAULT_MAX_FETCH_BYTES = 25 * 1024 * 1024  # 25 MB

# SSRF defense: hostnames polite_http is allowed to talk to. Every host
# listed here corresponds to a publisher in `src/casesignal/etl/sources/*.yaml`.
# IP-literal URLs (e.g. "http://169.254.169.254/...") bypass this allowlist by
# design — they're checked separately against the private-range denylist in
# _enforce_host_allowlist. Adding a new publisher source requires extending
# this set.
_DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset({
    # MD-county PD sites
    "harfordsheriff.org",
    "www.aacounty.org",
    "www.baltimorecountymd.gov",
    "www.ccso.us",
    "www.howardcountymd.gov",
    "www.wicomicosheriff.com",
    # Other state/local cold-case publishers
    "apps.colorado.gov",        # CO CBI
    "bci.utah.gov",             # UT BCI (WordPress)
    "mpdc.dc.gov",              # DC MPDC
    "www.doj.nh.gov",           # NH DOJ
    "www.ohioattorneygeneral.gov",  # OH AG
    "portal.dps.mn.gov",        # MN BCA (Phase 8 — static SOC PDFs + photos)
    "web.fdle.state.fl.us",     # FL FDLE JSF/PrimeFaces unsolved-cases portal
    "dps.arkansas.gov",         # AR ASP CID cold cases (WordPress)
    "media.ark.org",            # AR ASP case photos
    "oklahoma.gov",             # OK OSBI cold cases (AEM; pages + photos same host)
})


class RobotsTxtDisallowed(Exception):
    """Raised when robots.txt disallows a URL we tried to fetch."""


class FetchTooLarge(Exception):
    """Raised by fetch_to_file when the response stream exceeds max_bytes."""


class DisallowedHost(Exception):
    """Raised when a URL's host fails the SSRF allowlist or IP-range denylist.

    Two failure modes:
      - Hostname is not in `_DEFAULT_ALLOWED_HOSTS` (nor in the
        CASESIGNAL_HTTP_EXTRA_HOSTS env override). Closes the case where a
        compromised source YAML points input_path at an arbitrary URL.
      - URL host is an IP literal in a private / link-local / loopback /
        multicast range. Closes direct attempts to hit metadata services
        (169.254.169.254), internal RFC1918 addresses (10.x, 192.168.x),
        loopback (127.0.0.1), etc. — even via allowlisted hostnames is not
        defended (would require a custom transport for DNS-rebinding
        protection), only via direct IP-literal URLs.
    """


@dataclass
class _HostState:
    last_request_at: float = 0.0
    robots: urllib.robotparser.RobotFileParser | None = None
    robots_fetched: bool = False
    bypass_logged: bool = False


class PoliteHTTPClient:
    """HTTP client with UA, rate limiting, retry, and robots.txt enforcement.

    Construct once per scrape run; reuse across multiple GET/HEAD calls.
    Per-host state (last-request time + cached robots.txt) lives on the
    instance, so reusing the client is what makes rate-limiting work.
    """

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        rate_limit_seconds: float | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        max_fetch_bytes: int | None = None,
        bypass_robots_hosts: Iterable[str] | None = None,
        allowed_hosts: Iterable[str] | None = None,
        tls_impersonate: bool | None = None,
    ) -> None:
        self.user_agent: str = (
            user_agent or os.getenv("CASESIGNAL_SCRAPER_USER_AGENT") or _DEFAULT_USER_AGENT
        )
        self.rate_limit_seconds = (
            rate_limit_seconds
            if rate_limit_seconds is not None
            else float(
                os.getenv(
                    "CASESIGNAL_SCRAPER_RATE_LIMIT_SECONDS",
                    str(_DEFAULT_RATE_LIMIT_SECONDS),
                )
            )
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(
                os.getenv(
                    "CASESIGNAL_SCRAPER_TIMEOUT_SECONDS",
                    str(_DEFAULT_TIMEOUT_SECONDS),
                )
            )
        )
        self.max_retries = (
            max_retries
            if max_retries is not None
            else int(os.getenv("CASESIGNAL_SCRAPER_MAX_RETRIES", str(_DEFAULT_MAX_RETRIES)))
        )
        self.max_fetch_bytes = (
            max_fetch_bytes
            if max_fetch_bytes is not None
            else int(
                os.getenv(
                    "CASESIGNAL_SCRAPER_MAX_FETCH_BYTES",
                    str(_DEFAULT_MAX_FETCH_BYTES),
                )
            )
        )
        if bypass_robots_hosts is not None:
            self.bypass_robots_hosts: frozenset[str] = frozenset(
                h.lower() for h in bypass_robots_hosts
            )
        else:
            env_val = os.getenv("CASESIGNAL_BYPASS_ROBOTS_HOSTS", "")
            self.bypass_robots_hosts = frozenset(
                h.strip().lower() for h in env_val.split(",") if h.strip()
            )
        # SSRF allowlist: combine the static defaults with optional env
        # additions (CASESIGNAL_HTTP_EXTRA_HOSTS, comma-separated). Constructor
        # arg fully overrides both — tests pass a small allowlist that includes
        # localhost or a fake test domain.
        if allowed_hosts is not None:
            self.allowed_hosts: frozenset[str] = frozenset(h.lower() for h in allowed_hosts)
        else:
            extra_env = os.getenv("CASESIGNAL_HTTP_EXTRA_HOSTS", "")
            extra = {h.strip().lower() for h in extra_env.split(",") if h.strip()}
            self.allowed_hosts = _DEFAULT_ALLOWED_HOSTS | extra
        # TLS impersonation: some publishers sit behind Cloudflare Bot
        # Management, which fingerprints the TLS handshake (JA3/JA4) and 403s
        # Python's ssl stack regardless of User-Agent. When enabled we route
        # transport through curl_cffi (a real libcurl fingerprint) instead of
        # httpx. Everything else — allowlist, robots, rate limit, retry, size
        # cap — is transport-agnostic and unchanged. Redirects are followed
        # manually in the curl path so the SEC-E01 per-hop revalidation the
        # httpx event hook provides is preserved.
        if tls_impersonate is not None:
            self.tls_impersonate = tls_impersonate
        else:
            self.tls_impersonate = os.getenv(
                "CASESIGNAL_SCRAPER_TLS_IMPERSONATE", ""
            ).strip().lower() in ("1", "true", "yes")

        self._hosts: dict[str, _HostState] = {}
        self._curl: Any = None
        self._transport_errors: tuple[type[Exception], ...] = (
            httpx.TransportError,
            httpx.TimeoutException,
        )
        if self.tls_impersonate:
            from curl_cffi import requests as curl_requests
            from curl_cffi.requests import exceptions as curl_exceptions

            self._curl = curl_requests.Session()
            self._transport_errors = (curl_exceptions.RequestException,)
        # httpx client is always constructed: it is the default transport and
        # also backs _enforce_resolved_ip's world regardless of impersonation.
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            # SEC-E01: re-validate the host on EVERY send, including redirect
            # hops, so an open redirect (or a redirect to an internal address)
            # on an allowlisted publisher cannot smuggle the request elsewhere.
            event_hooks={"request": [self._validate_request_url]},
        )

    def __enter__(self) -> PoliteHTTPClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()
        if self._curl is not None:
            try:
                self._curl.close()
            except Exception:
                pass

    # ---------- public API ----------

    def get(self, url: str) -> httpx.Response:
        """GET with politeness + retry. Raises on 4xx; retries 5xx."""
        return self._request("GET", url)

    def head(self, url: str) -> httpx.Response:
        """HEAD with politeness + retry."""
        return self._request("HEAD", url)

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Polite POST. Same rate-limit/retry/robots posture as get()."""
        return self._request("POST", url, data=data, headers=headers)

    def fetch_to_file(
        self,
        url: str,
        dest_path: Path,
        *,
        max_bytes: int | None = None,
    ) -> Path:
        """Stream URL contents to dest_path. Aborts if size > max_bytes.

        On overflow: deletes the partial file and raises FetchTooLarge so
        callers don't end up with a half-downloaded photo on disk.
        """
        limit = max_bytes if max_bytes is not None else self.max_fetch_bytes
        host = urlparse(url).hostname or ""
        self._enforce_host_allowlist(host, url)
        self._enforce_robots(host, url)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        # Wait for rate-limit window before opening the stream.
        self._wait_for_rate_limit(host)

        try:
            if self.tls_impersonate:
                self._curl_stream_to_file(url, dest_path, limit)
            else:
                self._httpx_stream_to_file(url, dest_path, limit)
        except FetchTooLarge:
            raise
        except Exception:
            # On unexpected error, don't leave a partial file behind.
            try:
                dest_path.unlink()
            except (OSError, FileNotFoundError):
                pass
            raise
        finally:
            self._mark_request(host)

        return dest_path

    # ---------- internals ----------

    def _request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        host = urlparse(url).hostname or ""
        self._enforce_host_allowlist(host, url)
        self._enforce_robots(host, url)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit(host)
            try:
                if self.tls_impersonate:
                    response = self._curl_send(method, url, data=data, headers=headers)
                else:
                    response = self._client.request(method, url, data=data, headers=headers)
                self._mark_request(host)
            except self._transport_errors as exc:
                self._mark_request(host)
                last_exc = exc
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise

            if response.status_code >= 500 and attempt < self.max_retries:
                logger.info(
                    "polite_http retrying %s %s after %d (attempt %d/%d)",
                    method,
                    url,
                    response.status_code,
                    attempt + 1,
                    self.max_retries,
                )
                self._sleep_backoff(attempt)
                continue

            response.raise_for_status()
            return response

        raise RuntimeError(f"polite_http exhausted retries for {method} {url}; last={last_exc!r}")

    # ---------- curl_cffi transport (TLS impersonation) ----------

    _MAX_REDIRECTS = 10

    def _httpx_stream_to_file(self, url: str, dest_path: Path, limit: int) -> None:
        """Default streaming path: httpx with per-hop revalidation via hook."""
        bytes_written = 0
        with self._client.stream("GET", url) as response:
            if response.status_code >= 400:
                response.raise_for_status()
            with dest_path.open("wb") as f:
                for chunk in response.iter_bytes():
                    bytes_written += len(chunk)
                    if bytes_written > limit:
                        f.close()
                        try:
                            dest_path.unlink()
                        except OSError:
                            pass
                        raise FetchTooLarge(
                            f"Response from {url} exceeded {limit} bytes "
                            f"(stopped at {bytes_written}); partial file deleted"
                        )
                    f.write(chunk)

    def _curl_resolve_redirects(self, method: str, url: str) -> str:
        """Follow 3xx hops via curl_cffi WITHOUT auto-redirect, revalidating
        each hop's host (SEC-E01) exactly as the httpx event hook does for the
        default transport. Returns the final non-redirect URL.
        """
        current = url
        for _ in range(self._MAX_REDIRECTS + 1):
            host = urlparse(current).hostname or ""
            self._enforce_host_allowlist(host, current)
            self._enforce_resolved_ip(host, current)
            probe = self._curl.request(
                method,
                current,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
            if probe.status_code not in (301, 302, 303, 307, 308):
                return current
            location = probe.headers.get("location")
            if not location:
                return current
            current = urljoin(current, location)
        raise httpx.TooManyRedirects(
            f"exceeded {self._MAX_REDIRECTS} redirects for {url}",
            request=httpx.Request(method, url),
        )

    def _curl_send(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """One curl_cffi request, redirects followed with per-hop revalidation,
        wrapped in an httpx.Response so every caller stays transport-agnostic.
        """
        final_url = self._curl_resolve_redirects(method, url)
        merged = {"User-Agent": self.user_agent, **(headers or {})}
        r = self._curl.request(
            method,
            final_url,
            data=data,
            headers=merged,
            timeout=timeout if timeout is not None else self.timeout_seconds,
            allow_redirects=False,
        )
        return httpx.Response(
            status_code=r.status_code,
            headers=dict(r.headers),
            content=b"" if method == "HEAD" else r.content,
            request=httpx.Request(method, final_url),
        )

    def _curl_stream_to_file(self, url: str, dest_path: Path, limit: int) -> None:
        """Streaming download via curl_cffi with the same size ceiling and
        per-hop revalidation as the httpx path."""
        final_url = self._curl_resolve_redirects("GET", url)
        bytes_written = 0
        response = self._curl.request(
            "GET",
            final_url,
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
        try:
            if response.status_code >= 400:
                response.raise_for_status()
            with dest_path.open("wb") as f:
                for chunk in response.iter_content():
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > limit:
                        f.close()
                        try:
                            dest_path.unlink()
                        except OSError:
                            pass
                        raise FetchTooLarge(
                            f"Response from {url} exceeded {limit} bytes "
                            f"(stopped at {bytes_written}); partial file deleted"
                        )
                    f.write(chunk)
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _enforce_host_allowlist(self, host: str, url: str) -> None:
        """Reject URLs whose host fails the SSRF defense.

        Order of checks:
          1. IP-literal hosts are decoded and rejected if they fall in a
             private / link-local / loopback / multicast / reserved range.
             Catches direct attempts to reach AWS metadata (169.254.169.254),
             internal RFC1918 addresses (10.x, 172.16-31.x, 192.168.x),
             loopback (127.0.0.1), etc.
          2. Hostname hosts are rejected unless present in self.allowed_hosts.

        This method is the static check (allowlist + IP-literal denylist).
        DNS rebinding (an allowlisted hostname resolving to a private IP) is
        handled separately by ``_enforce_resolved_ip``, and redirect hops are
        re-checked via the request event hook (``_validate_request_url``).
        """
        if not host:
            raise DisallowedHost(f"URL missing host: {url!r}")

        # IP-literal path (covers IPv4 and IPv6 literals like [::1])
        host_for_ip = host.strip("[]")  # IPv6 URLs put brackets around host
        try:
            addr = ipaddress.ip_address(host_for_ip)
        except ValueError:
            addr = None
        if addr is not None:
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_reserved
                or addr.is_unspecified
            ):
                raise DisallowedHost(
                    f"polite_http refuses IP-literal in private/reserved range: "
                    f"{host} (url={url!r})"
                )
            # Public IP literal — still reject. We never legitimately need
            # to hit a bare public IP; every publisher we ingest from is
            # accessed via a hostname.
            raise DisallowedHost(
                f"polite_http refuses bare-IP URLs (use a hostname): "
                f"{host} (url={url!r})"
            )

        # Hostname path
        if host.lower() not in self.allowed_hosts:
            raise DisallowedHost(
                f"polite_http refuses non-allowlisted host: {host} (url={url!r}). "
                f"Add to _DEFAULT_ALLOWED_HOSTS in polite_http.py or set "
                f"CASESIGNAL_HTTP_EXTRA_HOSTS for one-off testing."
            )

    def _validate_request_url(self, request: httpx.Request) -> None:
        """httpx request event hook — runs before EVERY send, including each
        redirect hop (SEC-E01). Re-applies the static allowlist/IP-literal
        check and the DNS-rebinding resolve guard so a redirect cannot escape
        the allowlist or be pointed at an internal address.
        """
        host = request.url.host or ""
        url = str(request.url)
        self._enforce_host_allowlist(host, url)
        self._enforce_resolved_ip(host, url)

    def _enforce_resolved_ip(self, host: str, url: str) -> None:
        """DNS-rebinding guard (SEC-E01): reject when an allowlisted hostname
        resolves to a private/reserved address.

        Fails OPEN on resolution errors so a transient DNS hiccup doesn't break
        legitimate scraping. A residual TOCTOU window remains between this
        lookup and httpx's own resolution at connect time; closing it fully
        would require pinning the connection to the validated IP (accepted as a
        P3 residual). IP-literal hosts are already handled by the allowlist.
        """
        if not host:
            return
        try:
            ipaddress.ip_address(host.strip("[]"))
            return  # IP literal — _enforce_host_allowlist already rejected it
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return  # resolution failure: let the connection attempt fail naturally
        for info in infos:
            raw = str(info[4][0]).split("%")[0]  # strip IPv6 zone id if present
            try:
                addr = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_reserved
                or addr.is_unspecified
            ):
                raise DisallowedHost(
                    f"polite_http: allowlisted host {host} resolves to "
                    f"private/reserved address {raw} (DNS rebinding?) url={url!r}"
                )

    def _enforce_robots(self, host: str, url: str) -> None:
        state = self._hosts.setdefault(host, _HostState())
        if host.lower() in self.bypass_robots_hosts:
            if not state.bypass_logged:
                logger.warning(
                    "polite_http: bypassing robots.txt for %s (CASESIGNAL_BYPASS_ROBOTS_HOSTS)",
                    host,
                )
                state.bypass_logged = True
            return
        if not state.robots_fetched:
            # Fetch robots.txt with our own UA — urllib.robotparser's default
            # UA is filtered by some sites (Baltimore County's bot filter
            # serves it 403), which would falsely set disallow_all=True. We
            # bypass that by fetching with httpx and feeding text to .parse().
            robots_url = f"https://{host}/robots.txt"
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                if self.tls_impersonate:
                    response = self._curl_send("GET", robots_url, timeout=10.0)
                else:
                    response = self._client.get(robots_url, timeout=10.0)
            except Exception as exc:
                logger.info(
                    "polite_http: robots.txt at %s could not be fetched: %r" " (assuming allowed)",
                    host,
                    exc,
                )
                state.robots = None
            else:
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                    state.robots = parser
                elif response.status_code in (401, 403):
                    # Per RFC 9309, an authenticated/unauthorized response
                    # means treat as fully disallowed. We respect that.
                    parser.disallow_all = True  # type: ignore[attr-defined]
                    state.robots = parser
                else:
                    # 4xx (non-401/403) or 5xx: treat as missing → allow.
                    logger.info(
                        "polite_http: robots.txt at %s returned %d" " (assuming allowed)",
                        host,
                        response.status_code,
                    )
                    state.robots = None
            state.robots_fetched = True

        if state.robots is not None and not state.robots.can_fetch(self.user_agent, url):
            raise RobotsTxtDisallowed(
                f"robots.txt at {host} disallows {url} for UA {self.user_agent!r}"
            )

    def _wait_for_rate_limit(self, host: str) -> None:
        state = self._hosts.setdefault(host, _HostState())
        elapsed = time.monotonic() - state.last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)

    def _mark_request(self, host: str) -> None:
        state = self._hosts.setdefault(host, _HostState())
        state.last_request_at = time.monotonic()

    def _sleep_backoff(self, attempt: int) -> None:
        # 1s, 2s, 4s, 8s
        time.sleep(2**attempt)

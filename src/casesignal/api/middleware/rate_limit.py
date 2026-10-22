"""slowapi-based rate limiting keyed on authenticated API key (falls back to IP).

Two pieces work together:

* ``SlowAPIASGIMiddleware`` applies ``default_limits`` to every route that does
  NOT carry an explicit ``@limiter.limit`` decorator (admin/operator/methodology/
  health). Decorated routes are exempted by slowapi and keep their own limits, so
  there is no double-counting. Without this middleware ``default_limits`` is inert.
* ``_client_ip`` derives the bucketing IP. Behind a reverse proxy the TCP peer is
  the proxy, so per-IP buckets would collapse to one. We read X-Forwarded-For, but
  only by trusted-hop count (see ``RATE_LIMIT_TRUSTED_PROXY_HOPS``) so a client
  cannot spoof the leftmost entry to evade or frame a bucket.
"""

from __future__ import annotations

import os
from ipaddress import ip_address

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


def _trusted_proxy_hops() -> int:
    """Number of trusted reverse-proxy hops between us and the client.

    0 (default) = trust nothing, use the immediate peer IP. Behind Cloud Run /
    a load balancer set this to the count of proxies that append to
    X-Forwarded-For (Cloud Run *.run.app is typically 1). A malformed value
    degrades safely to 0.
    """
    raw = os.environ.get("RATE_LIMIT_TRUSTED_PROXY_HOPS", "0")
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _client_ip(request: Request) -> str:
    """Resolve the real client IP for rate bucketing.

    With N trusted hops, each trusted proxy appends the IP it received from, so
    the IP appended by the outermost trusted proxy (the real client) is at index
    ``-N`` of the X-Forwarded-For list. Entries the client prepends sit further
    left and are ignored. Falls back to the peer IP if the header is absent,
    shorter than N, or holds a non-IP at the trusted position.
    """
    hops = _trusted_proxy_hops()
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if len(parts) >= hops:
                candidate = parts[-hops]
                try:
                    ip_address(candidate)
                    return candidate
                except ValueError:
                    pass
    return get_remote_address(request)


def _key_func(request: Request) -> str:
    """Prefer the authenticated key id for rate bucketing; fall back to client IP.

    The default-limit middleware runs BEFORE the auth dependency, so for the
    undecorated authenticated routes (/admin/*, /operator/*) `api_key_id` is not
    yet set and the default bucket is keyed by client IP. This is intentional,
    not a regression (those routes previously had no limit at all):

    * The default limit exists to bound UNAUTHENTICATED floods — chiefly the
      /operator/snapshot amplification, whose cost is an outbound Supabase call
      made inside the auth dependency. Only a pre-auth limit can stop that, and
      an unauthenticated attacker has no key, so IP is the only stable bucket.
    * Keying the pre-auth bucket by the *presented* key/header instead would let
      an attacker rotate fake keys to mint unlimited buckets and bypass the
      limit, re-opening that DoS. So IP-keying is the correct choice here.

    Per-key buckets still apply wherever auth has already run by the time the
    limit is checked (i.e. routes carrying an explicit @limiter.limit decorator,
    which slowapi evaluates after dependency resolution).
    """
    # FastAPI's dependency_overrides may inject an AuthenticatedKey; read it from state if present
    key_id = getattr(request.state, "api_key_id", None)
    if key_id is not None:
        return f"key:{key_id}"
    return f"ip:{_client_ip(request)}"


def _limiter_kwargs() -> dict[str, object]:
    """Build Limiter kwargs from the environment.

    Storage is in-memory by default (local/dev, single process). When
    RATE_LIMIT_REDIS_URL is set (e.g. Upstash `rediss://…`), use it so limits
    are correct across Cloud Run instances. `swallow_errors=True` makes the
    limiter FAIL OPEN: if the store is unreachable, requests pass rather than
    500 — a rate limiter must never become a new outage source.
    """
    kwargs: dict[str, object] = {
        "key_func": _key_func,
        "default_limits": ["120/minute"],
        "swallow_errors": True,
    }
    redis_url = os.environ.get("RATE_LIMIT_REDIS_URL", "").strip()
    if redis_url:
        kwargs["storage_uri"] = redis_url
    return kwargs


limiter: Limiter = Limiter(**_limiter_kwargs())  # type: ignore[arg-type]


def register_rate_limiter(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    # Activates default_limits for routes without an explicit @limiter.limit
    # decorator. Decorated routes (e.g. the streaming photo endpoint) are exempted
    # by slowapi and pass straight through, so they keep their own limits and are
    # unaffected by the middleware.
    app.add_middleware(SlowAPIMiddleware)

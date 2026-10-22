"""Set the request scheme from X-Forwarded-Proto behind a TLS-terminating proxy.

Cloud Run terminates TLS at its managed proxy and forwards the original scheme in
``X-Forwarded-Proto``. Without honoring it the app sees ``scheme=http`` and emits
``http://`` in redirects / absolute URLs (e.g. the ``/healthz/`` trailing-slash
redirect).

This is a pure-ASGI middleware that rewrites ONLY ``scope["scheme"]``. It
deliberately does NOT touch the client address — unlike uvicorn's
``--proxy-headers`` (which rewrites the ASGI client from ``X-Forwarded-For`` and,
with ``--forwarded-allow-ips='*'``, would let a client spoof the IP used by the
rate-limit fallback). Rate-limit bucketing reads ``X-Forwarded-For`` itself with
an explicit trusted-hop count (``RATE_LIMIT_TRUSTED_PROXY_HOPS``) and otherwise
falls back to the true peer address, both of which this middleware leaves intact.

Scheme is not used for any access-control decision here, so trusting the header
is acceptable; it only affects URL/redirect generation.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class ForwardedProtoMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            for name, value in scope.get("headers") or []:
                if name == b"x-forwarded-proto":
                    proto = value.decode("latin-1").split(",")[0].strip().lower()
                    if proto in ("http", "https"):
                        scope = dict(scope)
                        scope["scheme"] = proto
                    break
        await self.app(scope, receive, send)

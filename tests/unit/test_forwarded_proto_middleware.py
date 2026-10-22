"""ForwardedProtoMiddleware sets scope["scheme"] from X-Forwarded-Proto and
nothing else — crucially, it must NOT touch the client address (that would
re-introduce the rate-limit spoofing the uvicorn --proxy-headers approach had).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from casesignal.api.middleware.forwarded_proto import ForwardedProtoMiddleware


def _run(
    headers: list[tuple[bytes, bytes]],
    scheme: str = "http",
    client: tuple[str, int] = ("10.0.0.1", 1234),
    scope_type: str = "http",
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def downstream(scope: Any, receive: Any, send: Any) -> None:
        captured["scope"] = scope

    async def receive() -> Any:  # pragma: no cover - not exercised
        return {}

    async def send(_: Any) -> None:  # pragma: no cover - not exercised
        return None

    mw = ForwardedProtoMiddleware(downstream)
    scope = {"type": scope_type, "headers": headers, "scheme": scheme, "client": client}
    asyncio.run(mw(scope, receive, send))
    return cast("dict[str, Any]", captured["scope"])


def test_sets_https_from_forwarded_proto() -> None:
    scope = _run([(b"x-forwarded-proto", b"https")])
    assert scope["scheme"] == "https"


def test_does_not_touch_client_address() -> None:
    scope = _run([(b"x-forwarded-proto", b"https")], client=("203.0.113.9", 5))
    assert scope["client"] == ("203.0.113.9", 5)


def test_no_header_leaves_scheme_unchanged() -> None:
    scope = _run([], scheme="http")
    assert scope["scheme"] == "http"


def test_takes_first_value_of_a_proto_list() -> None:
    scope = _run([(b"x-forwarded-proto", b"https, http")])
    assert scope["scheme"] == "https"


def test_ignores_garbage_proto_value() -> None:
    scope = _run([(b"x-forwarded-proto", b"ftp")], scheme="http")
    assert scope["scheme"] == "http"


def test_non_http_scope_passes_through_untouched() -> None:
    scope = _run([(b"x-forwarded-proto", b"https")], scheme="ws", scope_type="websocket")
    assert scope["scheme"] == "ws"

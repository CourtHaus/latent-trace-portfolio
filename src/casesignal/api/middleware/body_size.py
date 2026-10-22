"""MaxBodySize middleware — reject request bodies larger than a configured ceiling."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds max_bytes.

    Relies on the Content-Length header; a missing header is allowed to pass
    (chunked uploads are not currently part of the API surface, but callers
    without Content-Length still get validated downstream by Pydantic caps).
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length header."}, status_code=400)
            if size > self.max_bytes:
                return JSONResponse(
                    {"detail": f"Request body exceeds maximum size of {self.max_bytes} bytes."},
                    status_code=413,
                )
        return await call_next(request)

"""SEC-012: 500 responses must not leak internal exception content."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from casesignal.api.middleware.exception_handlers import register_exception_handlers


def test_sqlalchemy_error_returns_generic_500() -> None:
    """A SQLAlchemyError bubbling up from a route must NOT leak the DB message."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise SQLAlchemyError("DETAIL: password=hunter2 host=127.0.0.1")

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "An internal error occurred."}
    assert "password" not in resp.text
    assert "hunter2" not in resp.text


def test_unhandled_exception_returns_generic_500() -> None:
    """A generic Exception must produce a generic 500."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("secret internal detail: /etc/passwd leaked")

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/crash")
    assert resp.status_code == 500
    assert "secret internal detail" not in resp.text


def test_http_exception_passthrough() -> None:
    """Explicitly-raised HTTPException must still surface its detail."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    def nf() -> None:
        raise HTTPException(status_code=404, detail="nope")

    with TestClient(app) as c:
        resp = c.get("/not-found")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "nope"}

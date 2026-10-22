"""Generic exception handlers that avoid leaking internal state in 500s."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

_logger = logging.getLogger(__name__)

_GENERIC_500_BODY = {"detail": "An internal error occurred."}


async def _sqlalchemy_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    _logger.exception("Unhandled SQLAlchemyError on %s %s", request.method, request.url.path)
    return JSONResponse(_GENERIC_500_BODY, status_code=500)


async def _generic_handler(request: Request, exc: Exception) -> JSONResponse:
    _logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(_GENERIC_500_BODY, status_code=500)


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the SQLAlchemy and generic Exception handlers onto the app.

    FastAPI's own HTTPException handler remains untouched — only the
    uncaught paths get the generic body. RequestValidationError also
    continues to produce FastAPI's default 422 responses.
    """
    app.add_exception_handler(SQLAlchemyError, _sqlalchemy_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _generic_handler)

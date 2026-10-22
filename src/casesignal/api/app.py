from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from casesignal.api.dependencies.db import get_engine
from casesignal.api.middleware.body_size import MaxBodySizeMiddleware
from casesignal.api.middleware.exception_handlers import register_exception_handlers
from casesignal.api.middleware.forwarded_proto import ForwardedProtoMiddleware
from casesignal.api.middleware.rate_limit import register_rate_limiter
from casesignal.api.routes.admin.ingestion import router as admin_ingestion_router
from casesignal.api.routes.admin.keys import router as admin_keys_router
from casesignal.api.routes.cold_cases import router as cold_cases_router
from casesignal.api.routes.health import router as health_router
from casesignal.api.routes.methodology import router as methodology_router
from casesignal.api.routes.operator import router as operator_router
from casesignal.etl.config import settings
from casesignal.observability import init_sentry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    get_engine().dispose()


MAX_BODY_BYTES = 100 * 1024 * 1024  # 100 MB — admin uploads decode in-RAM; raise if a real source needs more.


def create_app() -> FastAPI:
    # Wire error reporting before anything else so failures during app
    # construction are captured too. No-op unless SENTRY_DSN is set.
    init_sentry("api")

    docs_enabled = settings.app_env in ("dev", "test")
    app = FastAPI(
        title="CaseSignal API",
        version="0.1.0",
        description="Read API for CaseSignal cold case data.",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=MAX_BODY_BYTES)
    register_exception_handlers(app)
    register_rate_limiter(app)

    _default_dev_origins = "http://localhost:3000"
    _origins_env = os.environ.get("FRONTEND_ORIGINS")
    # Read APP_ENV from the environment directly so tests can flip this with
    # monkeypatch.setenv without reloading the frozen-dataclass settings module.
    if os.environ.get("APP_ENV", "production") == "production" and not _origins_env:
        raise RuntimeError(
            "FRONTEND_ORIGINS must be set in production. "
            "Set a comma-separated list of allowed browser origins, e.g. "
            "FRONTEND_ORIGINS=https://app.example.com,https://admin.example.com"
        )
    _origins = [
        o.strip()
        for o in (_origins_env or _default_dev_origins).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
        allow_credentials=False,
        max_age=3600,
    )
    # Added last → outermost → runs first, so the corrected https scheme is in
    # place before routing (redirects) and everything else. Scheme-only; see the
    # middleware docstring for why this is decoupled from uvicorn --proxy-headers.
    app.add_middleware(ForwardedProtoMiddleware)

    app.include_router(health_router)

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(cold_cases_router)
    api_v1.include_router(admin_keys_router)
    api_v1.include_router(admin_ingestion_router)
    api_v1.include_router(methodology_router)
    api_v1.include_router(operator_router)
    app.include_router(api_v1)
    return app


app = create_app()

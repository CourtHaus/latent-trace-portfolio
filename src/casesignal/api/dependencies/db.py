from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.config import settings as etl_settings
from casesignal.etl.services.db import create_db_engine, create_session_factory


@lru_cache
def get_engine() -> Engine:
    # Prefer the pooled URL (Supabase transaction pooler) for the API so it can
    # scale out without exhausting Postgres connections. Workers and Alembic
    # keep using DATABASE_URL (direct) -- they need session-level features.
    if etl_settings.api_database_url:
        return create_db_engine(
            etl_settings.api_database_url,
            echo=etl_settings.sqlalchemy_echo,
            application_name="casesignal_api",
            use_nullpool=True,
        )
    return create_db_engine(
        etl_settings.database_url,
        echo=etl_settings.sqlalchemy_echo,
        pool_size=etl_settings.database_pool_size,
        max_overflow=etl_settings.database_max_overflow,
        pool_timeout=etl_settings.database_pool_timeout_seconds,
        application_name="casesignal_api",
        statement_timeout_ms=etl_settings.database_statement_timeout_ms,
        lock_timeout_ms=etl_settings.database_lock_timeout_ms,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_engine())


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()

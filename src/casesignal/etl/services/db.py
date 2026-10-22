from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


def create_db_engine(
    database_url: str,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    application_name: str | None = None,
    statement_timeout_ms: int | None = None,
    lock_timeout_ms: int | None = None,
    use_nullpool: bool = False,
) -> Engine:
    """
    Create and return an SQLAlchemy engine for the application database

    :param database_url: SQLAlchemy-compatible database URL.
    :param echo: Whether SQLAlchemy should log emitted SQL statements
    :return: Configured SQLAlchemy Engine instance.
    """
    engine_kwargs: dict[str, object] = {
        "echo": echo,
        "future": True,
        "pool_pre_ping": True,
    }

    if not database_url.startswith("sqlite"):
        if use_nullpool:
            # Behind a transaction-mode pooler (Supabase Supavisor, :6543):
            # let the pooler multiplex; don't hold idle SQLAlchemy connections.
            # statement/lock timeouts are NOT sent as libpq `options` here --
            # poolers drop that startup param -- they live as role-level defaults.
            engine_kwargs["poolclass"] = NullPool
            connect_args = _build_postgres_connect_args(
                application_name=application_name,
                statement_timeout_ms=None,
                lock_timeout_ms=None,
            )
        else:
            engine_kwargs.update(
                {
                    "pool_size": pool_size,
                    "max_overflow": max_overflow,
                    "pool_timeout": pool_timeout,
                }
            )
            connect_args = _build_postgres_connect_args(
                application_name=application_name,
                statement_timeout_ms=statement_timeout_ms,
                lock_timeout_ms=lock_timeout_ms,
            )
        if connect_args:
            engine_kwargs["connect_args"] = connect_args

    return create_engine(database_url, **engine_kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """
    Create and return a session factory bound to the provided engine.
    :param engine: SQLAlchemy Engine instance
    :return:  SQLAlchemy sessionmaker configured for Session objects.
    """
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def test_connection(engine: Engine) -> None:
    """
    Verify that the database connection is healthy.

    Raises:
        Any database exception encountered while executing the test query.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def dispose_engine(engine: Engine) -> None:
    """Dispose of the engine and its underlying connection cool"""
    engine.dispose()


def _build_postgres_connect_args(
    application_name: str | None,
    statement_timeout_ms: int | None,
    lock_timeout_ms: int | None,
) -> dict[str, str]:
    connect_args: dict[str, str] = {}
    option_parts: list[str] = []

    if application_name:
        connect_args["application_name"] = application_name

    if statement_timeout_ms is not None and statement_timeout_ms > 0:
        option_parts.append(f"-c statement_timeout={statement_timeout_ms}")

    if lock_timeout_ms is not None and lock_timeout_ms > 0:
        option_parts.append(f"-c lock_timeout={lock_timeout_ms}")

    if option_parts:
        connect_args["options"] = " ".join(option_parts)

    return connect_args

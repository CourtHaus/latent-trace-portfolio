"""create_db_engine: NullPool mode for the transaction-pooler path."""

from __future__ import annotations

from sqlalchemy.pool import NullPool, QueuePool

from casesignal.etl.services.db import create_db_engine

_PG_URL = "postgresql+psycopg2://u:p@localhost:6543/db"


def test_default_uses_queuepool() -> None:
    engine = create_db_engine(_PG_URL)
    assert isinstance(engine.pool, QueuePool)


def test_nullpool_mode_uses_nullpool() -> None:
    engine = create_db_engine(_PG_URL, use_nullpool=True)
    assert isinstance(engine.pool, NullPool)


def test_nullpool_path_omits_libpq_timeout_options() -> None:
    # The nullpool branch builds connect_args with timeouts suppressed (poolers
    # drop the libpq `options` startup param; timeouts live as role-level
    # defaults), while still passing application_name.
    from casesignal.etl.services.db import _build_postgres_connect_args

    connect_args = _build_postgres_connect_args(
        application_name="casesignal_api",
        statement_timeout_ms=None,
        lock_timeout_ms=None,
    )
    assert "options" not in connect_args
    assert connect_args["application_name"] == "casesignal_api"

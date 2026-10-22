"""Single source of truth for which database the test suite may touch.

The integration suite has no per-test isolation; fixtures seed-and-commit. To
keep the live local DB safe, conftest redirects DATABASE_URL to a dedicated
test DB and refuses to run unless that DB carries a test-only sentinel table.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg2://casesignal:casesignal@localhost:5433/casesignal_test"
)
SENTINEL_TABLE = "public._casesignal_test_sentinel"


def resolve_test_database_url() -> str:
    """Resolve the test DB URL. TEST_DATABASE_URL wins; never the live URL."""
    return os.environ.get("TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL


def _marker_exists(conn: Connection, qualified_name: str) -> bool:
    return (
        conn.execute(text("SELECT to_regclass(:n)"), {"n": qualified_name}).scalar()
        is not None
    )


def has_sentinel(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return _marker_exists(conn, SENTINEL_TABLE)
    finally:
        engine.dispose()


def enforce_test_database(url: str) -> None:
    """Raise RuntimeError unless `url` points at a reachable, sentinel-stamped test DB.

    Connection failures (DB missing / Postgres down / wrong port) are converted
    into the same friendly RuntimeError so the actionable guidance is shown
    instead of a raw OperationalError traceback -- this is the common first-run
    case the message is written for.
    """
    try:
        present = has_sentinel(url)
    except OperationalError as exc:
        raise RuntimeError(
            f"REFUSING to run: cannot connect to test database '{url}'. Is Postgres "
            f"running on the expected port, and does the test DB exist? "
            f"Run tools/create_test_db.sh to create + migrate casesignal_test, or "
            f"set TEST_DATABASE_URL to a reachable, sentinel-stamped test DB."
        ) from exc
    if not present:
        raise RuntimeError(
            f"REFUSING to run: target database '{url}' is not a CaseSignal test "
            f"database (missing {SENTINEL_TABLE}). This guard prevents tests from "
            f"mutating the live DB. Run tools/create_test_db.sh to create "
            f"casesignal_test, or set TEST_DATABASE_URL to a sentinel-stamped test DB."
        )

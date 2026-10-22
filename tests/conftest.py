from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = _REPO_ROOT / "src"
for _p in (str(_REPO_ROOT), str(SRC_PATH)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- Test-DB isolation (Layer 1: redirect) --------------------------------
# Force the test process onto the dedicated test DB BEFORE any casesignal
# import reads settings. We never use the original DATABASE_URL as the target,
# so a live URL in .env cannot leak into the suite.
from tests.support.db_guard import resolve_test_database_url  # noqa: E402

os.environ["DATABASE_URL"] = resolve_test_database_url()
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("KEY_HMAC_SECRET", "test-hmac-secret")


def pytest_configure(config: object) -> None:  # noqa: ARG001
    # Layer 2: abort the whole session if the target is not a sentinel-stamped
    # test DB (runs before collection / any fixture commits).
    import pytest

    from tests.support.db_guard import enforce_test_database

    try:
        enforce_test_database(os.environ["DATABASE_URL"])
    except RuntimeError as exc:
        raise pytest.UsageError(str(exc)) from exc

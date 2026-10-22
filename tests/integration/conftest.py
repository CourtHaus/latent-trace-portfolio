from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from casesignal.api.app import create_app

if TYPE_CHECKING:
    from tests.integration._seed import CaseSpec, SeededCorpus, SeedFn

# Single source of truth; the root conftest.py has already redirected
# os.environ["DATABASE_URL"] to the dedicated test DB (casesignal_test) and a
# sentinel guard has refused the session if it is not a real test database.
from tests.support.db_guard import resolve_test_database_url

DATABASE_URL = resolve_test_database_url()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    # Schema is migrated out-of-band: tools/create_test_db.sh locally, the
    # "Apply migrations" step in CI. We deliberately do NOT run alembic here —
    # alembic's fileConfig() disables existing loggers, which breaks caplog
    # assertions in unit tests that run later in the same session.
    engine = create_engine(DATABASE_URL)
    yield engine
    # Tests run against the dedicated test DB (casesignal_test); seed fixtures
    # commit canary corpora. Clean leaked test-seed source_systems at session
    # end so they don't accumulate.
    # Best-effort — never fail the suite on teardown.
    try:
        from tools.clean_test_sources import clean_test_sources

        clean_test_sources(engine)
    except Exception:
        pass
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def public_client() -> Iterator[TestClient]:
    """TestClient with no dependency overrides — exercises public routes as
    an anonymous visitor. Use this for tests of routes that are public after
    the A0 auth-split. Admin-gated routes should use `admin_client` (defined
    in tests/integration/security/conftest.py)."""
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seed(db_engine: Engine) -> Iterator[SeedFn]:
    """Function-scoped: yields a seed(source_code, cases) callable and tears
    down every corpus it created after the test (even on failure)."""
    from casesignal.etl.services.db import create_session_factory
    from tests.integration._seed import seed_corpus

    sf = create_session_factory(db_engine)
    created: list[SeededCorpus] = []

    def _seed(
        source_code: str,
        cases: list[CaseSpec],
        *,
        source_state: str | None = None,
    ) -> SeededCorpus:
        corpus = seed_corpus(
            sf,
            source_code=source_code,
            cases=cases,
            source_state=source_state,
        )
        created.append(corpus)
        return corpus

    yield _seed
    for corpus in reversed(created):
        corpus.teardown()


@pytest.fixture(scope="module")
def seeded_corpus(db_engine: Engine) -> Iterator[SeedFn]:
    """Module-scoped: yields a seed(source_code, cases) callable for read-only
    suites that seed one small corpus per module. Torn down at module exit."""
    from casesignal.etl.services.db import create_session_factory
    from tests.integration._seed import seed_corpus

    sf = create_session_factory(db_engine)
    created: list[SeededCorpus] = []

    def _seed(
        source_code: str,
        cases: list[CaseSpec],
        *,
        source_state: str | None = None,
    ) -> SeededCorpus:
        corpus = seed_corpus(
            sf,
            source_code=source_code,
            cases=cases,
            source_state=source_state,
        )
        created.append(corpus)
        return corpus

    yield _seed
    for corpus in reversed(created):
        corpus.teardown()


@pytest.fixture(autouse=True)
def _isolated_correlation_base_rates() -> Iterator[None]:
    """Correlation base rates are TTL-cached per process; without clearing,
    one test's seeded corpus poisons every later test that scores leads."""
    from casesignal.correlation.base_rates import clear_base_rates_cache

    clear_base_rates_cache()
    yield
    clear_base_rates_cache()

"""Integration tests for tools.clean_test_sources raw-table cleanup.

DB-backed: require a reachable local Postgres via the db_engine fixture.
Per-DV raw tables have no FK to etl.dataset_version, so clean_test_sources
must drop them explicitly or stale test tables reach the Supabase sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from tests.integration._seed import CaseSpec
from tools.clean_test_sources import clean_test_sources

if TYPE_CHECKING:
    from tests.integration._seed import SeedFn


def _case() -> CaseSpec:
    return CaseSpec(source_case_id="C-001", case_name="Test Case", state="MD")


def _make_raw_table(engine: Engine, dv: int, base: str = "cold_case_test") -> str:
    """Create raw_cold_case.<base>_dv<dv> with one row. Returns the table name."""
    name = f"{base}_dv{dv}"
    with engine.begin() as c:
        c.execute(
            sa.text(
                f'CREATE TABLE raw_cold_case."{name}" '
                "(dataset_version_id INTEGER NOT NULL, payload TEXT)"
            )
        )
        c.execute(
            sa.text(
                f'INSERT INTO raw_cold_case."{name}" (dataset_version_id, payload) '
                "VALUES (:dv, 'seed')"
            ),
            {"dv": dv},
        )
    return name


def _table_exists(engine: Engine, name: str) -> bool:
    with engine.begin() as c:
        return bool(
            c.execute(
                sa.text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'raw_cold_case' AND table_name = :n"
                ),
                {"n": name},
            ).first()
        )


def test_clean_drops_test_raw_table(db_engine: Engine, seed: SeedFn) -> None:
    corpus = seed("CLEANUP_TEST", [_case()])
    name = _make_raw_table(db_engine, corpus.dataset_version_id)
    assert _table_exists(db_engine, name)

    summary = clean_test_sources(db_engine)

    assert not _table_exists(db_engine, name)
    assert name in summary["raw_tables"]


def test_dry_run_reports_but_preserves_raw_table(db_engine: Engine, seed: SeedFn) -> None:
    corpus = seed("CLEANUP_TEST", [_case()])
    name = _make_raw_table(db_engine, corpus.dataset_version_id)

    summary = clean_test_sources(db_engine, dry_run=True)

    assert _table_exists(db_engine, name)  # not dropped
    assert name in summary["raw_tables"]  # but reported

    # Real run so the dry-run seed's raw table doesn't linger past the test.
    clean_test_sources(db_engine)
    assert not _table_exists(db_engine, name)


def test_non_test_raw_table_is_untouched(db_engine: Engine, seed: SeedFn) -> None:
    # CLEANUP_KEEP does NOT match test|integration, so clean_test_sources must
    # leave it (and its raw table) alone. The seed fixture still tears down its
    # FK rows; we drop its raw table by hand since teardown() won't.
    keep = seed("CLEANUP_KEEP", [_case()])
    keep_name = _make_raw_table(db_engine, keep.dataset_version_id, base="cold_case_keep")

    # A test source that SHOULD be cleaned, to prove selectivity.
    test_corpus = seed("CLEANUP_TEST", [_case()])
    test_name = _make_raw_table(db_engine, test_corpus.dataset_version_id)

    summary = clean_test_sources(db_engine)

    assert _table_exists(db_engine, keep_name)  # preserved
    assert keep_name not in summary["raw_tables"]
    assert not _table_exists(db_engine, test_name)  # cleaned

    # Drop the kept raw table so it doesn't leak (fixture teardown won't).
    with db_engine.begin() as c:
        c.execute(sa.text(f'DROP TABLE IF EXISTS raw_cold_case."{keep_name}"'))

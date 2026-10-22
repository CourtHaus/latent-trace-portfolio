"""Remove test-seed source_system rows (and their cascade) from a database.

Integration tests run against the local DB (there is no separate test
database), and the ones that commit leak source_system rows like ``TEST_CODE``,
``*_TEST``, ``FDLE_TRANSFORM_TEST``. Over many runs their orphan
dataset_versions accumulate. The Supabase sync's pre-flight refuses to push
these to production; this tool removes them so the sync passes, and the
integration conftest calls ``clean_test_sources`` at session teardown so they
never accumulate.

Usage:
  DATABASE_URL=... uv run python tools/clean_test_sources.py [--dry-run]
"""

from __future__ import annotations

import os
import sys
from typing import Any

from sqlalchemy import Engine, create_engine, text

# Source codes matching this (case-insensitive) regex are treated as test seeds.
# No real source code contains "test" or "integration".
TEST_SOURCE_PATTERN = "test|integration"

_CHILD_TABLES = (
    "cold_case.victim",
    "cold_case.contact",
    "cold_case.case_extractions",
    "cold_case.extraction_job",
    "cold_case.case_photo",
    "cold_case.geocoding_job",
    "cold_case.extraction_review",
)


def _test_raw_tables(c: Any, dv: list[int]) -> list[str]:
    """Raw tables in raw_cold_case whose name ends in _dv<N> for a deleted dv.

    Per-DV raw tables (raw_cold_case.<base>_dv<N>) have no FK back to
    etl.dataset_version, so they are not removed by the metadata cascade. We
    discover real table names from information_schema (adapter-agnostic) and
    match the universal _dv<N> suffix exactly, so _dv5 never matches _dv50.
    """
    if not dv:
        return []
    existing = [
        r[0]
        for r in c.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'raw_cold_case'"
            )
        )
    ]
    suffixes = tuple(f"_dv{n}" for n in dv)
    return sorted(name for name in existing if name.endswith(suffixes))


def clean_test_sources(engine: Engine, *, dry_run: bool = False) -> dict[str, Any]:
    """Delete test-pattern source_systems + cascade. Returns a summary dict."""
    with engine.begin() as c:
        ss = [
            r[0]
            for r in c.execute(
                text("SELECT source_system_id FROM etl.source_system WHERE source_code ~* :p"),
                {"p": TEST_SOURCE_PATTERN},
            )
        ]
        if not ss:
            return {"sources": [], "dataset_versions": 0, "cases": 0, "raw_tables": []}
        codes = [
            r[0]
            for r in c.execute(
                text("SELECT source_code FROM etl.source_system WHERE source_system_id = ANY(:x)"),
                {"x": ss},
            )
        ]
        dv = [
            r[0]
            for r in c.execute(
                text("SELECT dataset_version_id FROM etl.dataset_version WHERE source_system_id = ANY(:x)"),
                {"x": ss},
            )
        ]
        ids = (
            [
                r[0]
                for r in c.execute(
                    text("SELECT case_id FROM cold_case.cases WHERE dataset_version_id = ANY(:x)"),
                    {"x": dv},
                )
            ]
            if dv
            else []
        )
        raw_tables = _test_raw_tables(c, dv)
        summary = {
            "sources": codes,
            "dataset_versions": len(dv),
            "cases": len(ids),
            "raw_tables": raw_tables,
        }
        if dry_run:
            return summary
        for tbl in _CHILD_TABLES:
            if ids:
                c.execute(text(f"DELETE FROM {tbl} WHERE case_id = ANY(:x)"), {"x": ids})  # noqa: S608 - literal table
        if dv:
            c.execute(text("DELETE FROM cold_case.cases WHERE dataset_version_id = ANY(:x)"), {"x": dv})
            c.execute(
                text(
                    "DELETE FROM etl.ingestion_run_stage WHERE ingestion_run_id IN "
                    "(SELECT ingestion_run_id FROM etl.ingestion_run WHERE dataset_version_id = ANY(:x))"
                ),
                {"x": dv},
            )
            c.execute(text("DELETE FROM etl.ingestion_run WHERE dataset_version_id = ANY(:x)"), {"x": dv})
            c.execute(text("DELETE FROM etl.dataset_version WHERE dataset_version_id = ANY(:x)"), {"x": dv})
        c.execute(text("DELETE FROM etl.source_system WHERE source_system_id = ANY(:x)"), {"x": ss})
        for name in raw_tables:
            # name comes from information_schema filtered to raw_cold_case — never
            # user input — and the DROP is hard-scoped to that schema.
            c.execute(text(f'DROP TABLE IF EXISTS raw_cold_case."{name}"'))  # noqa: S608
        return summary


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1
    dry_run = "--dry-run" in sys.argv[1:]
    summary = clean_test_sources(create_engine(url), dry_run=dry_run)
    if not summary["sources"]:
        print("No test-pattern source_system rows found.")
        return 0
    verb = "would delete" if dry_run else "deleted"
    print(
        f"{verb} {len(summary['sources'])} test source(s) {summary['sources']}, "
        f"{summary['dataset_versions']} dataset_versions, {summary['cases']} cases, "
        f"{len(summary['raw_tables'])} raw tables."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

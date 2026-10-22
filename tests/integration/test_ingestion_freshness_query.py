"""Integration test for the ingestion-freshness SQL: a source that has attempted
an ingest but never published must still surface (last_ingest=None), so the
monitor can flag it. Uses db_session, which rolls back per test."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tools.ingestion_freshness import _QUERY

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


def _insert_source(db_session: Session, code: str, status: str) -> None:
    ss = db_session.execute(
        text(
            "INSERT INTO etl.source_system (source_code, source_name) "
            "VALUES (:c, :n) RETURNING source_system_id"
        ),
        {"c": code, "n": f"{code} test"},
    ).scalar_one()
    db_session.execute(
        text(
            "INSERT INTO etl.dataset_version "
            "(source_system_id, source_year, source_state, source_label, source_hash, "
            " ingestion_status) "
            "VALUES (:ss, 2026, 'ZZ', :label, :hash, :status)"
        ),
        {"ss": ss, "label": f"{code} dv", "hash": f"freshtest-{code}", "status": status},
    )


def test_query_surfaces_never_published_source(db_session: Session) -> None:
    # Draft-only source = attempted ingest, never published (e.g. a first ingest
    # that failed before publish). It must appear with last_ingest=None so
    # build_report flags it; a 'published'-only join would silently drop it.
    _insert_source(db_session, "FRESHTEST_DRAFT", "draft")
    _insert_source(db_session, "FRESHTEST_PUB", "published")

    rows = {r.source_code: r for r in db_session.execute(text(_QUERY)).all()}

    assert "FRESHTEST_DRAFT" in rows, "never-published source dropped from query"
    assert rows["FRESHTEST_DRAFT"].last_ingest is None
    assert rows["FRESHTEST_DRAFT"].published_cases == 0

    # A published source still reports normally with a timestamp.
    assert "FRESHTEST_PUB" in rows
    assert rows["FRESHTEST_PUB"].last_ingest is not None

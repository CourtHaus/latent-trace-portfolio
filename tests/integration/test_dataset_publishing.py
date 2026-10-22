"""Integration test: publishing a dataset_version archives the prior published
one for the same source, so the public corpus is never double-counted.

Uses a rollback-only session — nothing inserted here is ever committed, so no
cleanup is needed and the live/test corpus is untouched.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.services.dataset_publishing import _mark_dataset_version_published

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


@pytest.fixture
def rb_session() -> Iterator[Session]:
    """A session that is always rolled back; inserted rows never persist."""
    engine = create_engine(os.environ["DATABASE_URL"])
    session_local = sessionmaker(engine)
    s = session_local()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
    engine.dispose()


def _insert_source(s: Session, code: str, name: str) -> int:
    return int(
        s.execute(
            text(
                "INSERT INTO etl.source_system (source_code, source_name)"
                " VALUES (:code, :name) RETURNING source_system_id"
            ),
            {"code": code, "name": name},
        ).scalar_one()
    )


def _insert_dv(s: Session, ss: int, label: str, status: str, vhash: str) -> int:
    return int(
        s.execute(
            text(
                "INSERT INTO etl.dataset_version"
                " (source_system_id, source_year, source_label, source_hash, ingestion_status)"
                " VALUES (:ss, 2026, :label, :hash, :status) RETURNING dataset_version_id"
            ),
            {"ss": ss, "label": label, "hash": vhash, "status": status},
        ).scalar_one()
    )


def _statuses_by_source(s: Session, ss: int) -> dict[int, str]:
    return {
        row[0]: row[1]
        for row in s.execute(
            text(
                "SELECT dataset_version_id, ingestion_status FROM etl.dataset_version"
                " WHERE source_system_id = :ss"
            ),
            {"ss": ss},
        ).all()
    }


def test_publish_archives_prior_version_of_same_slice(rb_session: Session) -> None:
    """Re-ingesting a slice (same source_label, new source_hash) and publishing
    the new version must archive the prior published version of that slice."""
    s = rb_session
    ss = _insert_source(s, "PUBTEST", "Publish Archive Test")
    dv_old = _insert_dv(s, ss, "Slice A", "published", "hash-a-old")
    dv_new = _insert_dv(s, ss, "Slice A", "validated", "hash-a-new")

    _mark_dataset_version_published(s, dv_new)

    statuses = _statuses_by_source(s, ss)
    assert statuses[dv_old] == "archived", "prior version of the same slice must archive"
    assert statuses[dv_new] == "published"


def test_publish_preserves_sibling_slice_of_same_source(rb_session: Session) -> None:
    """A source can publish multiple slices at once (e.g. DC MPDC's 2020 slice
    and 1951-2019 slice share one source_code with distinct source_labels).
    Publishing a new version of one slice must NOT archive a different live
    slice of the same source."""
    s = rb_session
    ss = _insert_source(s, "PUBTEST", "Multi-slice Source")
    sibling = _insert_dv(s, ss, "Slice B (1951-2019)", "published", "hash-b")
    a_old = _insert_dv(s, ss, "Slice A (2020)", "published", "hash-a-old")
    a_new = _insert_dv(s, ss, "Slice A (2020)", "validated", "hash-a-new")

    _mark_dataset_version_published(s, a_new)

    statuses = _statuses_by_source(s, ss)
    assert statuses[a_old] == "archived", "prior version of the SAME slice must archive"
    assert statuses[a_new] == "published"
    assert statuses[sibling] == "published", "a different live slice must be preserved"


def test_publish_leaves_other_sources_untouched(rb_session: Session) -> None:
    s = rb_session
    ss_a = _insert_source(s, "PUBTEST_A", "Source A")
    ss_b = _insert_source(s, "PUBTEST_B", "Source B")
    other_published = _insert_dv(s, ss_b, "Slice A", "published", "hash-b1")
    a_old = _insert_dv(s, ss_a, "Slice A", "published", "hash-a-old")
    a_new = _insert_dv(s, ss_a, "Slice A", "validated", "hash-a-new")

    _mark_dataset_version_published(s, a_new)

    # A different source's published version must NOT be archived, even with an
    # identical source_label (the source_system_id differs).
    assert (
        s.execute(
            text(
                "SELECT ingestion_status FROM etl.dataset_version"
                " WHERE dataset_version_id = :id"
            ),
            {"id": other_published},
        ).scalar_one()
        == "published"
    )
    assert _statuses_by_source(s, ss_a)[a_old] == "archived"

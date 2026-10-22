"""Integration tests for the shared cold-case source registration helper.

Covers the contract every scraped adapter now relies on: create source_system +
dataset_version (draft) + ingestion_run, set them on the context, reuse the
dataset_version for an unchanged source_hash, and create a new one when it
changes.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import (
    register_cold_case_source,
    register_file_based_cold_case_source,
)

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_SOURCE_CODE = "SHARED_REG_TEST"


@pytest.fixture
def sf() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = sessionmaker(engine)
    try:
        yield factory
    finally:
        with factory() as s:
            s.execute(
                text(
                    "DELETE FROM etl.ingestion_run WHERE dataset_version_id IN ("
                    " SELECT dataset_version_id FROM etl.dataset_version WHERE source_system_id IN ("
                    "  SELECT source_system_id FROM etl.source_system WHERE source_code = :c))"
                ),
                {"c": _SOURCE_CODE},
            )
            s.execute(
                text(
                    "DELETE FROM etl.dataset_version WHERE source_system_id IN ("
                    " SELECT source_system_id FROM etl.source_system WHERE source_code = :c)"
                ),
                {"c": _SOURCE_CODE},
            )
            s.execute(
                text("DELETE FROM etl.source_system WHERE source_code = :c"), {"c": _SOURCE_CODE}
            )
            s.commit()
        engine.dispose()


def _ctx(factory: sessionmaker[Session]) -> PipelineContext:
    ctx = PipelineContext(
        source_key="shared_reg_test",
        source_code=_SOURCE_CODE,
        source_name="Shared Reg Test",
        source_family="cold_case",
        source_year=2026,
        source_state="ZZ",
        source_path=Path("/dev/null"),
        logger=logging.getLogger("test_source_registration"),
    )
    ctx.set_metadata("session_factory", factory)
    ctx.set_metadata(
        "source_definition",
        {"description": "desc", "metadata": {"source_url": "https://example.test/src"}},
    )
    return ctx


def test_registers_and_sets_context(sf: sessionmaker[Session]) -> None:
    ctx = _ctx(sf)
    register_cold_case_source(
        ctx, source_hash="hash-a", source_file_name="https://example.test/page", log_label="Test"
    )
    assert ctx.source_system_id is not None
    assert ctx.dataset_version_id is not None
    assert ctx.ingestion_run_id is not None

    with sf() as s:
        status = s.execute(
            text(
                "SELECT ingestion_status FROM etl.dataset_version WHERE dataset_version_id = :id"
            ),
            {"id": ctx.dataset_version_id},
        ).scalar_one()
    assert status == "draft"


def test_reuses_dataset_version_for_same_hash(sf: sessionmaker[Session]) -> None:
    ctx1 = _ctx(sf)
    register_cold_case_source(
        ctx1, source_hash="same-hash", source_file_name="u", log_label="Test"
    )
    ctx2 = _ctx(sf)
    register_cold_case_source(
        ctx2, source_hash="same-hash", source_file_name="u", log_label="Test"
    )
    assert ctx1.dataset_version_id == ctx2.dataset_version_id


def test_new_dataset_version_on_changed_hash(sf: sessionmaker[Session]) -> None:
    ctx1 = _ctx(sf)
    register_cold_case_source(ctx1, source_hash="hash-1", source_file_name="u", log_label="Test")
    ctx2 = _ctx(sf)
    register_cold_case_source(ctx2, source_hash="hash-2", source_file_name="u", log_label="Test")
    assert ctx1.dataset_version_id != ctx2.dataset_version_id


def _file_ctx(
    factory: sessionmaker[Session],
    source_path: Path,
    metadata: dict[str, object] | None = None,
) -> PipelineContext:
    ctx = PipelineContext(
        source_key="shared_reg_test",
        source_code=_SOURCE_CODE,
        source_name="Shared Reg Test",
        source_family="cold_case",
        source_year=2026,
        source_state="ZZ",
        source_path=source_path,
        logger=logging.getLogger("test_source_registration"),
    )
    ctx.set_metadata("session_factory", factory)
    ctx.set_metadata("source_definition", {"description": "desc", "metadata": metadata or {}})
    return ctx


def test_file_based_register_and_reuse_same_file(
    sf: sessionmaker[Session], tmp_path: Path
) -> None:
    """File-based: source_hash comes from the file bytes; an unchanged file
    reuses the dataset_version."""
    f = tmp_path / "harvest.csv"
    f.write_text("a,b\n1,2\n")

    ctx1 = _file_ctx(sf, f)
    register_file_based_cold_case_source(ctx1, log_label="Test")
    assert ctx1.dataset_version_id is not None

    ctx2 = _file_ctx(sf, f)
    register_file_based_cold_case_source(ctx2, log_label="Test")
    assert ctx2.dataset_version_id == ctx1.dataset_version_id


def test_file_based_fallback_reuse_when_hash_unavailable(
    sf: sessionmaker[Session], tmp_path: Path
) -> None:
    """If the file is gone (no computable hash), the (year, state, file_name)
    fallback reuses the prior version instead of inserting a duplicate."""
    f = tmp_path / "data.csv"
    f.write_text("x\n")
    ctx1 = _file_ctx(sf, f)
    register_file_based_cold_case_source(ctx1, log_label="Test")
    dv = ctx1.dataset_version_id

    f.unlink()  # file gone -> resolve_source_hash returns None
    ctx2 = _file_ctx(sf, f)  # same .name ("data.csv"), no longer exists
    register_file_based_cold_case_source(ctx2, log_label="Test")
    assert ctx2.dataset_version_id == dv


def test_file_based_backfills_and_reuses_null_hash_version(
    sf: sessionmaker[Session], tmp_path: Path
) -> None:
    """A version registered before its hash was available (source_hash NULL):
    a later run WITH a hash must backfill that row and REUSE it, not insert a
    duplicate (which would violate uq_dataset_version_source_hash)."""
    # First run with the file absent -> NULL-hash version via the fallback path.
    missing = tmp_path / "harvest.json"
    ctx0 = _file_ctx(sf, missing)
    register_file_based_cold_case_source(ctx0, log_label="Test")
    dv = ctx0.dataset_version_id
    with sf() as s:
        h0 = s.execute(
            text("SELECT source_hash FROM etl.dataset_version WHERE dataset_version_id=:id"),
            {"id": dv},
        ).scalar_one()
    assert h0 is None  # registered without a hash

    # Second run now has a hash (same source_path.name) -> backfill + reuse.
    ctx1 = _file_ctx(sf, missing, metadata={"source_hash": "backfilled-hash"})
    register_file_based_cold_case_source(ctx1, log_label="Test")
    assert ctx1.dataset_version_id == dv, "must reuse the backfilled row, not insert a dup"
    with sf() as s:
        h1 = s.execute(
            text("SELECT source_hash FROM etl.dataset_version WHERE dataset_version_id=:id"),
            {"id": dv},
        ).scalar_one()
        total = s.execute(
            text(
                "SELECT count(*) FROM etl.dataset_version WHERE source_system_id ="
                " (SELECT source_system_id FROM etl.source_system WHERE source_code=:c)"
            ),
            {"c": _SOURCE_CODE},
        ).scalar_one()
    assert h1 == "backfilled-hash"  # hash backfilled onto the existing row
    assert total == 1  # no duplicate row created

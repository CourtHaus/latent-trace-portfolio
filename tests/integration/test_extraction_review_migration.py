from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


@pytest.fixture
def engine() -> Any:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    return create_engine(db_url)


def test_extraction_review_table_exists(engine: Any) -> None:
    with engine.connect() as conn:
        table_name = conn.execute(
            text("SELECT to_regclass('cold_case.extraction_review')")
        ).scalar_one()

    assert table_name == "cold_case.extraction_review"


def test_extraction_review_table_has_review_columns(engine: Any) -> None:
    with engine.connect() as conn:
        cols = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='cold_case' AND table_name='extraction_review'"
                )
            )
        }

    expected = {
        "case_id",
        "prompt_hash",
        "prompt_tier",
        "reviewer",
        "verdict_date",
        "verdict_address",
        "verdict_age",
        "verdict_gender",
        "notes",
        "created_at",
    }
    assert expected.issubset(cols), f"Missing: {expected - cols}"
    # Race was removed in migration 0014 — see feedback-no-llm-race-inference.
    assert "verdict_race" not in cols, (
        "verdict_race column must remain dropped; migration 0014 removed it."
    )

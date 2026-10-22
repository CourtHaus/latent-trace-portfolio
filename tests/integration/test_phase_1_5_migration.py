"""Verify migration 0003's table + view shape (after 0014 dropped Tier-2 race).

Originally this file asserted that 0003's Tier-2 race columns landed on
``case_extractions`` and the ``case_extractions_current`` view. Migration
0014 (see feedback-no-llm-race-inference) dropped those columns — so this
file now asserts the opposite: the race columns must remain absent.

Source-provided ``cold_case.victim.race`` is unaffected and still verified.
"""

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


_TIER2_RACE_COLUMNS = {
    "victim_race_text",
    "victim_race_raw_phrase",
    "victim_race_source_start",
    "victim_race_source_end",
    "victim_race_low_confidence",
}


def test_tier2_race_columns_absent_from_case_extractions(engine: Any) -> None:
    """Migration 0014 dropped these columns; they must not return."""
    with engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='cold_case' AND table_name='case_extractions'"
                )
            )
        }
    assert cols.isdisjoint(_TIER2_RACE_COLUMNS), (
        f"Tier-2 race columns reappeared on case_extractions: "
        f"{cols & _TIER2_RACE_COLUMNS}"
    )


def test_victim_race_column_still_exists_on_victim_baseline(engine: Any) -> None:
    """Source-provided race in cold_case.victim is unaffected by 0014.

    Correlation scoring and the public race filter both read this column.
    """
    with engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='cold_case' AND table_name='victim'"
                )
            )
        }
    assert "race" in cols
    assert "race_source" in cols


def test_extractions_current_view_does_not_expose_race(engine: Any) -> None:
    with engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='cold_case' "
                    "AND table_name='case_extractions_current'"
                )
            )
        }
    assert cols.isdisjoint(_TIER2_RACE_COLUMNS), (
        f"View must not surface race: {cols & _TIER2_RACE_COLUMNS}"
    )


def test_extractions_current_view_is_queryable(engine: Any) -> None:
    """Functional check: the recreated view body executes without error."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT incident_date_text, victim_gender_text"
                " FROM cold_case.case_extractions_current LIMIT 1"
            )
        )
        _ = result.fetchall()

"""Unit tests for the Tier-2 auto-review heuristics."""

from __future__ import annotations

from scripts.auto_review_tier2 import _check_gender, build_review_query


def test_check_gender_matches_source_aliases() -> None:
    assert _check_gender("male", "M", None) == "correct"
    assert _check_gender("female", "F", None) == "correct"


def test_check_gender_flags_conflicting_source_aliases() -> None:
    assert _check_gender("male", "F", None) == "incorrect"


def test_review_query_summarizes_victims_before_joining_extractions() -> None:
    query, params = build_review_query(prompt_hash_prefix=None)

    sql = str(query)
    assert "WITH victim_demo AS" in sql
    assert "COUNT(*) AS victim_count" in sql
    assert "CASE WHEN COUNT(*) = 1 THEN MAX(gender) ELSE NULL END AS src_gender" in sql
    assert "LEFT JOIN victim_demo v ON v.case_id = e.case_id" in sql
    assert "LEFT JOIN cold_case.victim" not in sql
    assert params == {"rev": "auto-review"}


def test_review_query_does_not_select_race_columns() -> None:
    """Belt-and-suspenders: race is gone from the schema, so the SELECT must
    never reference it. If a future change brings race back into auto-review,
    this catches it."""
    query, _ = build_review_query(prompt_hash_prefix=None)
    sql = str(query).lower()
    assert "race" not in sql

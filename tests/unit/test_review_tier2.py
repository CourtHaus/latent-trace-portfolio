"""Unit tests for the Tier-2 interactive review query."""

from __future__ import annotations

from scripts.review_tier2 import build_review_query


def test_review_query_defaults_to_all_tier2_prompt_hashes() -> None:
    query, params = build_review_query(
        state=None,
        limit=None,
        randomize=False,
        resume=False,
        reviewer="reviewer@example.test",
        prompt_hash_prefix=None,
    )

    sql = str(query)
    assert "e.prompt_tier = 2" in sql
    assert "LEFT(e.prompt_hash" not in sql
    assert params == {}


def test_review_query_applies_prompt_hash_prefix_when_requested() -> None:
    query, params = build_review_query(
        state=None,
        limit=None,
        randomize=False,
        resume=False,
        reviewer="reviewer@example.test",
        prompt_hash_prefix="abc123",
    )

    assert "LEFT(e.prompt_hash, :hp_len) = :hp" in str(query)
    assert params == {"hp": "abc123", "hp_len": 6}

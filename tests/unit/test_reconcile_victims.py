"""Unit tests for the pure reconciliation planner.

`plan_reconciliation(existing, roster)` is a PURE function (no DB). It decides
how to correct `cold_case.victim` rows against a Tier-2 narrative roster.

Hard invariants exercised here:
  - empty roster -> no-op
  - never delete an existing row unless it is garbled AND roster has >1 victim
  - destructive replace only when len(roster) > 1
  - matched existing rows are kept + linked, never deleted
  - dropped victims are recovered (created) only when the roster legitimately
    has more victims than existing
"""

from __future__ import annotations

from typing import Any

from casesignal.extraction.cold_case.reconcile_victims import plan_reconciliation


def test_a_single_keep_and_link() -> None:
    existing = [{"victim_id": 1, "first_name": "Jane", "last_name": "Doe"}]
    roster = [{"ordinal": 1, "name": "Jane Doe"}]
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == [] and plan.creates == []
    assert plan.links == [(1, 1)]


def test_b_garbled_split_recovers_dropped() -> None:
    existing = [{"victim_id": 9, "first_name": "Joseph and Betty", "last_name": "Selby"}]
    roster = [{"ordinal": 1, "name": "Joseph Selby"}, {"ordinal": 2, "name": "Betty Selby"}]
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == [9]
    assert {c["name"] for c in plan.creates} == {"Joseph Selby", "Betty Selby"}


def test_general_dropped_victim_recovered() -> None:
    existing = [{"victim_id": 5, "first_name": "Alex", "last_name": "Exampleton"}]
    roster = [{"ordinal": 1, "name": "Alex Exampleton"}, {"ordinal": 2, "name": "Robin Sampleton"}]
    plan = plan_reconciliation(existing, roster)
    assert 5 not in plan.deletes
    assert any(c["name"] == "Robin Sampleton" for c in plan.creates)
    assert (5, 1) in plan.links


def test_d_under_detection_no_destruction() -> None:
    existing = [{"victim_id": 1, "first_name": "A", "last_name": "B"},
                {"victim_id": 2, "first_name": "C", "last_name": "D"}]
    roster = [{"ordinal": 1, "name": "A B"}]
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == []


def test_false_garbled_guard_single_victim_name_with_and() -> None:
    existing = [{"victim_id": 1, "first_name": "Bonnie and Clyde", "last_name": "Co"}]
    roster = [{"ordinal": 1, "name": "Bonnie and Clyde Co"}]
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == [] and plan.creates == []
    assert plan.links == [(1, 1)]


def test_empty_roster_is_noop() -> None:
    existing = [{"victim_id": 1, "first_name": "Jane", "last_name": "Doe"}]
    assert plan_reconciliation(existing, []) == plan_reconciliation(existing, [])  # stable
    p = plan_reconciliation(existing, [])
    assert p.deletes == [] and p.creates == [] and p.links == []


# --- additional edge tests ---


def test_empty_existing_roster_of_two_creates_both() -> None:
    """No existing rows + roster of 2 -> both created (recover, nothing deleted)."""
    existing: list[dict[str, Any]] = []
    roster = [{"ordinal": 1, "name": "Jane Doe"}, {"ordinal": 2, "name": "John Smith"}]
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == []
    assert {c["name"] for c in plan.creates} == {"Jane Doe", "John Smith"}
    # nothing to link to existing rows
    assert plan.links == []


def test_matched_existing_not_duplicated_as_create() -> None:
    """A roster victim matching an existing row is linked, never re-created."""
    existing = [{"victim_id": 7, "first_name": "Alex", "last_name": "Exampleton"}]
    roster = [{"ordinal": 1, "name": "Alex Exampleton"}, {"ordinal": 2, "name": "Robin Sampleton"}]
    plan = plan_reconciliation(existing, roster)
    # Alex Exampleton already exists -> must NOT appear in creates
    assert all(c["name"] != "Alex Exampleton" for c in plan.creates)
    assert (7, 1) in plan.links


def test_garbled_ampersand_splits() -> None:
    """'&' is a garbled signal just like ' and '."""
    existing = [{"victim_id": 3, "first_name": "Ann & Helen", "last_name": "Larkin"}]
    roster = [{"ordinal": 1, "name": "Ann Larkin"}, {"ordinal": 2, "name": "Helen Larkin"}]
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == [3]
    assert {c["name"] for c in plan.creates} == {"Ann Larkin", "Helen Larkin"}


def test_one_to_one_mismatch_no_spurious_create() -> None:
    """existing=1, roster=1, names differ -> link the lone row, do NOT create.

    A 1:1 name mismatch is an LLM re-spelling, not a dropped victim. Creating a
    second row here would duplicate the single real victim.
    """
    existing = [{"victim_id": 2, "first_name": "Robert", "last_name": "Jones"}]
    roster = [{"ordinal": 1, "name": "Bob Jones"}]
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == []
    assert plan.creates == []
    assert plan.links == [(2, 1)]


def test_empty_existing_single_roster_creates_one() -> None:
    """existing=[], roster=[{ordinal:1, name:'Jane Doe'}] -> one create, no deletes, no links."""
    existing: list[dict[str, Any]] = []
    roster = [{"ordinal": 1, "name": "Jane Doe"}]
    plan = plan_reconciliation(existing, roster)
    assert len(plan.creates) == 1
    assert plan.creates[0]["name"] == "Jane Doe"
    assert plan.deletes == []
    assert plan.links == []

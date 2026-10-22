"""Integration test for apply_reconciliation against a real DB.

Reproduces the canonical garbled multi-victim case (case 6471 shape):
one garbled victim row ``first_name="Joseph and Betty" last_name="Selby"`` plus
two ``victim_extraction`` roster rows. After reconciliation the garbled row is
gone, two proper victim rows exist (NO age/gender — Phase 1 is identity only),
and both ``victim_extraction`` rows are linked by ``victim_id``.

Run with:
  uv run pytest tests/integration/test_reconcile_victims_apply.py
  (the harness redirects to the casesignal_test database automatically)
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.extraction.cold_case.reconcile_victims import (
    apply_reconciliation,
    plan_reconciliation,
)
from tests.integration._seed import CaseSpec, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


def test_garbled_case_is_split_and_linked(db_session: Session, seed: SeedFn) -> None:
    corpus = seed(
        "RECONCILE_GARBLED",
        [
            CaseSpec(
                source_case_id="joseph-and-betty-selby-1981",
                case_name="Joseph and Betty Selby",
                state="ZZ",
                about_text="Joseph Selby and Betty Selby were killed in 1981.",
                victims=[VictimSpec(first_name="Joseph and Betty", last_name="Selby")],
            )
        ],
    )
    case_id = corpus.case_ids["joseph-and-betty-selby-1981"]

    # The garbled existing victim row.
    existing_rows = (
        db_session.execute(
            text(
                "SELECT victim_id, first_name, last_name "
                "  FROM cold_case.victim WHERE case_id = :cid"
            ),
            {"cid": case_id},
        )
        .mappings()
        .all()
    )
    existing: list[dict[str, Any]] = [dict(r) for r in existing_rows]
    assert len(existing) == 1
    garbled_victim_id = existing[0]["victim_id"]

    # Two roster rows in victim_extraction (ordinals 1, 2).
    roster = [
        {"ordinal": 1, "name": "Joseph Selby"},
        {"ordinal": 2, "name": "Betty Selby"},
    ]
    for entry in roster:
        db_session.execute(
            text("""
                INSERT INTO cold_case.victim_extraction
                    (case_id, victim_ordinal, model_id, prompt_hash,
                     name_text, name_raw_phrase, name_source_start, name_source_end)
                VALUES (:cid, :ord, 'test-model', 'RECONCILE_HASH',
                        :name, :name, 0, 0)
            """),
            {"cid": case_id, "ord": entry["ordinal"], "name": entry["name"]},
        )
    db_session.commit()

    # Plan + apply + commit.
    plan = plan_reconciliation(existing, roster)
    assert plan.deletes == [garbled_victim_id]
    apply_reconciliation(
        db_session, case_id, plan, model_id="test-model", prompt_hash="RECONCILE_HASH"
    )
    db_session.commit()

    # The garbled row is gone; two proper rows exist with NO demographics.
    victims = (
        db_session.execute(
            text(
                "SELECT victim_id, first_name, last_name, gender, age_text "
                "  FROM cold_case.victim WHERE case_id = :cid "
                " ORDER BY first_name"
            ),
            {"cid": case_id},
        )
        .mappings()
        .all()
    )
    assert garbled_victim_id not in {v["victim_id"] for v in victims}
    names = {(v["first_name"], v["last_name"]) for v in victims}
    assert names == {("Betty", "Selby"), ("Joseph", "Selby")}
    for v in victims:
        assert v["gender"] is None
        assert v["age_text"] is None

    # Both victim_extraction rows are linked to the new victim rows by ordinal.
    links = (
        db_session.execute(
            text(
                "SELECT ve.victim_ordinal, ve.victim_id, v.first_name, v.last_name "
                "  FROM cold_case.victim_extraction ve "
                "  JOIN cold_case.victim v ON v.victim_id = ve.victim_id "
                " WHERE ve.case_id = :cid AND ve.prompt_hash = 'RECONCILE_HASH' "
                " ORDER BY ve.victim_ordinal"
            ),
            {"cid": case_id},
        )
        .mappings()
        .all()
    )
    assert len(links) == 2
    assert (links[0]["victim_ordinal"], links[0]["first_name"]) == (1, "Joseph")
    assert (links[1]["victim_ordinal"], links[1]["first_name"]) == (2, "Betty")


def test_link_update_scoped_to_current_extraction(db_session: Session, seed: SeedFn) -> None:
    """apply_reconciliation must only update victim_id on rows that match the
    current (model_id, prompt_hash) — older rows for the same (case_id, ordinal)
    must be left untouched.

    Scenario: single existing victim row; single-entry roster.  Two
    victim_extraction rows share (case_id, ordinal=1) but differ in
    prompt_hash: 'CURRENT_HASH' (being reconciled now) and 'OLD_HASH' (a prior
    extraction version).  After apply_reconciliation(..., prompt_hash='CURRENT_HASH'):
      - 'CURRENT_HASH' row has victim_id populated (linked).
      - 'OLD_HASH'     row's victim_id is still NULL (untouched).
    """
    corpus = seed(
        "RECONCILE_SCOPE",
        [
            CaseSpec(
                source_case_id="scope-test-victim-1999",
                case_name="Scope Test Victim",
                state="ZZ",
                about_text="Jane Doe was killed in 1999.",
                victims=[VictimSpec(first_name="Jane", last_name="Doe")],
            )
        ],
    )
    case_id = corpus.case_ids["scope-test-victim-1999"]

    existing_rows = (
        db_session.execute(
            text(
                "SELECT victim_id, first_name, last_name "
                "  FROM cold_case.victim WHERE case_id = :cid"
            ),
            {"cid": case_id},
        )
        .mappings()
        .all()
    )
    existing: list[dict[str, Any]] = [dict(r) for r in existing_rows]
    assert len(existing) == 1

    # Insert TWO victim_extraction rows for ordinal=1: one "current", one "old".
    for ph in ("CURRENT_HASH", "OLD_HASH"):
        db_session.execute(
            text("""
                INSERT INTO cold_case.victim_extraction
                    (case_id, victim_ordinal, model_id, prompt_hash,
                     name_text, name_raw_phrase, name_source_start, name_source_end)
                VALUES (:cid, 1, 'test-model', :ph,
                        'Jane Doe', 'Jane Doe', 0, 0)
            """),
            {"cid": case_id, "ph": ph},
        )
    db_session.commit()

    # Reconcile using CURRENT_HASH only.
    roster = [{"ordinal": 1, "name": "Jane Doe"}]
    plan = plan_reconciliation(existing, roster)
    apply_reconciliation(
        db_session, case_id, plan, model_id="test-model", prompt_hash="CURRENT_HASH"
    )
    db_session.commit()

    # CURRENT_HASH row must be linked.
    current_vid = db_session.execute(
        text(
            "SELECT victim_id FROM cold_case.victim_extraction"
            " WHERE case_id = :cid AND victim_ordinal = 1 AND prompt_hash = 'CURRENT_HASH'"
        ),
        {"cid": case_id},
    ).scalar_one()
    assert current_vid is not None, "CURRENT_HASH row should have been linked"

    # OLD_HASH row must remain NULL (untouched by this reconciliation run).
    old_vid = db_session.execute(
        text(
            "SELECT victim_id FROM cold_case.victim_extraction"
            " WHERE case_id = :cid AND victim_ordinal = 1 AND prompt_hash = 'OLD_HASH'"
        ),
        {"cid": case_id},
    ).scalar_one_or_none()
    assert old_vid is None, "OLD_HASH row must not be touched by reconciliation for CURRENT_HASH"

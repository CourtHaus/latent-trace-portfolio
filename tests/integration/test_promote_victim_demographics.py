"""Integration tests for promote_victim_demographics against a real DB.

Invariants under test (spec §4):
  - fill NULL only — never overwrite a non-NULL source value (incl. 'unknown')
  - skip low-confidence extraction fields
  - skip rows not linked to a victim (victim_id IS NULL handled by seeding
    only linked rows; unlinked is covered by the no-extraction case)
  - gender promoted only when 'M'/'F'
  - promoted columns get *_source = 'tier2'
  - case_id scoping limits the write set
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy import text

from casesignal.etl.services.db import create_session_factory
from casesignal.extraction.cold_case.promote_demographics import (
    main,
    promote_victim_demographics,
)
from tests.integration._seed import (
    CaseSpec,
    SeedFn,
    VictimExtractionSpec,
    VictimSpec,
)

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


@pytest.fixture
def session_factory(db_engine: Any) -> Any:
    return create_session_factory(db_engine)


def _victim_row(session_factory: Any, victim_first_name: str) -> dict[str, Any]:
    with session_factory() as s:
        row = s.execute(
            text(
                "SELECT age_text, age_num, gender, age_source, gender_source "
                "FROM cold_case.victim WHERE first_name = :fn"
            ),
            {"fn": victim_first_name},
        ).mappings().one()
        return dict(row)


def test_promotion_fills_null_age_and_gender(seed: SeedFn, session_factory: Any) -> None:
    corpus = seed(
        "promo-fill",
        [
            CaseSpec(
                source_case_id="p1",
                case_name="Promo Fill",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoFillVictim",
                        last_name="One",
                        age_text=None,
                        gender=None,
                        extraction=VictimExtractionSpec(
                            age_text="34",
                            age_raw_phrase="34-year-old",
                            age_source_start=10,
                            age_source_end=21,
                            gender_text="F",
                            gender_raw_phrase="she",
                            gender_source_start=30,
                            gender_source_end=33,
                        ),
                    )
                ],
            )
        ],
    )
    try:
        with session_factory() as s:
            counts = promote_victim_demographics(s, case_id=corpus.case_ids["p1"])
            s.commit()
        assert counts.ages_filled == 1
        assert counts.genders_filled == 1
        row = _victim_row(session_factory, "PromoFillVictim")
        assert row["age_text"] == "34"
        assert row["age_num"] == 34  # generated column follows age_text
        assert row["age_source"] == "tier2"
        assert row["gender"] == "F"
        assert row["gender_source"] == "tier2"
        # Re-run: promoted columns are now non-NULL, so nothing changes.
        with session_factory() as s:
            second = promote_victim_demographics(s, case_id=corpus.case_ids["p1"])
            s.commit()
        assert second.ages_filled == 0
        assert second.genders_filled == 0
        row2 = _victim_row(session_factory, "PromoFillVictim")
        assert row2 == row
    finally:
        corpus.teardown()


def test_promotion_never_overwrites_source_values(seed: SeedFn, session_factory: Any) -> None:
    corpus = seed(
        "promo-keep",
        [
            CaseSpec(
                source_case_id="p2",
                case_name="Promo Keep",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoKeepVictim",
                        last_name="Two",
                        age_text="60",
                        age_source="source",
                        gender="unknown",  # non-NULL: must survive
                        gender_source="source",
                        extraction=VictimExtractionSpec(
                            age_text="34", gender_text="F"
                        ),
                    )
                ],
            )
        ],
    )
    try:
        with session_factory() as s:
            promote_victim_demographics(s)
            s.commit()
        row = _victim_row(session_factory, "PromoKeepVictim")
        assert row["age_text"] == "60"
        assert row["age_source"] == "source"
        assert row["gender"] == "unknown"
        assert row["gender_source"] == "source"
    finally:
        corpus.teardown()


def test_promotion_skips_low_confidence_fields(seed: SeedFn, session_factory: Any) -> None:
    corpus = seed(
        "promo-lowconf",
        [
            CaseSpec(
                source_case_id="p3",
                case_name="Promo LowConf",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoLowConfVictim",
                        last_name="Three",
                        extraction=VictimExtractionSpec(
                            age_text="34",
                            age_low_confidence=True,
                            gender_text="F",
                            gender_low_confidence=True,
                        ),
                    )
                ],
            )
        ],
    )
    try:
        with session_factory() as s:
            promote_victim_demographics(s)
            s.commit()
        row = _victim_row(session_factory, "PromoLowConfVictim")
        assert row["age_text"] is None
        assert row["gender"] is None
        assert row["age_source"] is None
        assert row["gender_source"] is None
    finally:
        corpus.teardown()


def test_promotion_guards_gender_vocabulary(seed: SeedFn, session_factory: Any) -> None:
    corpus = seed(
        "promo-vocab",
        [
            CaseSpec(
                source_case_id="p4",
                case_name="Promo Vocab",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoVocabVictim",
                        last_name="Four",
                        extraction=VictimExtractionSpec(gender_text="female"),
                    )
                ],
            )
        ],
    )
    try:
        with session_factory() as s:
            promote_victim_demographics(s)
            s.commit()
        row = _victim_row(session_factory, "PromoVocabVictim")
        assert row["gender"] is None  # 'female' not in ('M','F') — not promoted
    finally:
        corpus.teardown()


def test_promotion_case_id_scoping(seed: SeedFn, session_factory: Any) -> None:
    corpus = seed(
        "promo-scope",
        [
            CaseSpec(
                source_case_id="p5a",
                case_name="Promo In Scope",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoScopeVictimA",
                        last_name="Five",
                        extraction=VictimExtractionSpec(age_text="20"),
                    )
                ],
            ),
            CaseSpec(
                source_case_id="p5b",
                case_name="Promo Out Of Scope",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoScopeVictimB",
                        last_name="Six",
                        extraction=VictimExtractionSpec(age_text="40"),
                    )
                ],
            ),
        ],
    )
    try:
        in_scope_case_id = corpus.case_ids["p5a"]
        with session_factory() as s:
            counts = promote_victim_demographics(s, case_id=in_scope_case_id)
            s.commit()
        assert counts.ages_filled == 1
        row_a = _victim_row(session_factory, "PromoScopeVictimA")
        row_b = _victim_row(session_factory, "PromoScopeVictimB")
        assert row_a["age_text"] == "20"
        assert row_b["age_text"] is None
    finally:
        corpus.teardown()


def test_promotion_ignores_victims_without_extraction(seed: SeedFn, session_factory: Any) -> None:
    corpus = seed(
        "promo-noext",
        [
            CaseSpec(
                source_case_id="p7",
                case_name="Promo No Extraction",
                state="MD",
                victims=[
                    VictimSpec(first_name="PromoNoExtVictim", last_name="Eight")
                ],
            )
        ],
    )
    try:
        with session_factory() as s:
            promote_victim_demographics(s, case_id=corpus.case_ids["p7"])
            s.commit()
        row = _victim_row(session_factory, "PromoNoExtVictim")
        assert row["age_text"] is None
        assert row["gender"] is None
        assert row["age_source"] is None
        assert row["gender_source"] is None
    finally:
        corpus.teardown()


def test_promotion_skips_null_extraction_values(seed: SeedFn, session_factory: Any) -> None:
    corpus = seed(
        "promo-nullvals",
        [
            CaseSpec(
                source_case_id="p8",
                case_name="Promo Null Values",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoNullValsVictim",
                        last_name="Nine",
                        extraction=VictimExtractionSpec(),  # row exists, all values NULL
                    )
                ],
            )
        ],
    )
    try:
        with session_factory() as s:
            promote_victim_demographics(s, case_id=corpus.case_ids["p8"])
            s.commit()
        row = _victim_row(session_factory, "PromoNullValsVictim")
        assert row["age_text"] is None
        assert row["gender"] is None
        assert row["age_source"] is None
        assert row["gender_source"] is None
    finally:
        corpus.teardown()


def test_cli_dry_run_writes_nothing(seed: SeedFn, session_factory: Any) -> None:
    # main() builds its own engine from os.environ["DATABASE_URL"] (rewritten
    # to the test DB by conftest), so the read-back via session_factory is a
    # deliberately separate connection observing post-rollback DB state.
    corpus = seed(
        "promo-dry",
        [
            CaseSpec(
                source_case_id="p9",
                case_name="Promo Dry",
                state="MD",
                victims=[
                    VictimSpec(
                        first_name="PromoDryVictim",
                        last_name="Ten",
                        extraction=VictimExtractionSpec(age_text="25"),
                    )
                ],
            )
        ],
    )
    try:
        rc = main(["--dry-run", "--case-id", str(corpus.case_ids["p9"])])
        assert rc == 0
        row = _victim_row(session_factory, "PromoDryVictim")
        assert row["age_text"] is None  # rolled back
    finally:
        corpus.teardown()

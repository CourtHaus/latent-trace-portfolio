"""Integration tests for extraction persistence against a real DB."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.extraction.cold_case.extract_case import (
    EXTRACTOR_VERSION,
    CaseExtraction,
    ExtractedField,
)
from casesignal.extraction.cold_case.persistence import (
    extraction_exists_for,
    find_cases_needing_extraction,
    insert_extraction,
)
from tests.integration._seed import CaseSpec, SeedFn

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


def _case(source_case_id: str) -> CaseSpec:
    return CaseSpec(
        source_case_id=source_case_id,
        case_name=f"Extraction Persistence Test {source_case_id}",
        state="ZZ",
        city="Extractville",
        about_text="Victim was shot inside a residence.",
    )


def _case_for_state(source_case_id: str, state: str) -> CaseSpec:
    return CaseSpec(
        source_case_id=source_case_id,
        case_name=f"Extraction Persistence Test {source_case_id}",
        state=state,
        city="Extractville",
        about_text="Victim was shot inside a residence.",
    )


def _good_extraction(
    case_id: int, *, prompt_hash: str = "TESTHASH", model_id: str = "TEST_MODEL"
) -> CaseExtraction:
    return CaseExtraction(
        case_id=case_id,
        weapon=ExtractedField(
            value="firearm",
            raw_phrase="shot to death",
            source_start=10,
            source_end=23,
            low_confidence=False,
        ),
        location_type=ExtractedField(
            value="residence",
            raw_phrase="in the apartment",
            source_start=40,
            source_end=56,
            low_confidence=False,
        ),
        extractor_version="TEST_" + EXTRACTOR_VERSION,
        prompt_hash=prompt_hash,
        model_id=model_id,
        raw_llm_response={"stub": True},
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        notes=None,
    )


def test_insert_extraction_writes_row(db_session: Session, seed: SeedFn) -> None:
    corpus = seed("EXTRACTION_PERSISTENCE_INSERT", [_case("xp-insert")])
    case_id = corpus.case_ids["xp-insert"]

    insert_extraction(db_session, _good_extraction(case_id))
    db_session.commit()

    row = (
        db_session.execute(
            text(
                "SELECT weapon, location_type, weapon_source_start FROM cold_case.case_extractions "
                "WHERE case_id = :cid AND extractor_version = :ev"
            ),
            {"cid": case_id, "ev": "TEST_" + EXTRACTOR_VERSION},
        )
        .mappings()
        .one()
    )
    assert row["weapon"] == "firearm"
    assert row["location_type"] == "residence"
    assert row["weapon_source_start"] == 10


def test_extraction_exists_for_returns_true_after_write(db_session: Session, seed: SeedFn) -> None:
    corpus = seed("EXTRACTION_PERSISTENCE_EXISTS", [_case("xp-exists")])
    case_id = corpus.case_ids["xp-exists"]

    assert extraction_exists_for(db_session, case_id, "TESTHASH", "TEST_MODEL") is False
    insert_extraction(db_session, _good_extraction(case_id))
    db_session.commit()
    assert extraction_exists_for(db_session, case_id, "TESTHASH", "TEST_MODEL") is True
    assert extraction_exists_for(db_session, case_id, "OTHERHASH", "TEST_MODEL") is False


def test_find_cases_needing_extraction_excludes_already_extracted(
    db_session: Session,
    seed: SeedFn,
) -> None:
    corpus = seed(
        "EXTRACTION_PERSISTENCE_FIND",
        [_case("xp-find-a"), _case("xp-find-b")],
    )
    first = corpus.case_ids["xp-find-a"]
    second = corpus.case_ids["xp-find-b"]

    insert_extraction(db_session, _good_extraction(first))
    db_session.commit()

    remaining = find_cases_needing_extraction(
        db_session,
        prompt_hash="TESTHASH",
        model_id="TEST_MODEL",
        dataset_version_id=corpus.dataset_version_id,
    )
    ids = {row.case_id for row in remaining}
    assert first not in ids
    assert second in ids


def test_find_cases_needing_extraction_is_prompt_tier_aware(
    db_session: Session,
    seed: SeedFn,
) -> None:
    corpus = seed(
        "EXTRACTION_PERSISTENCE_FIND_TIER",
        [_case("xp-find-tier-a"), _case("xp-find-tier-b")],
    )
    first = corpus.case_ids["xp-find-tier-a"]
    second = corpus.case_ids["xp-find-tier-b"]

    insert_extraction(db_session, _good_extraction(first))
    db_session.commit()

    remaining = find_cases_needing_extraction(
        db_session,
        prompt_hash="TESTHASH",
        model_id="TEST_MODEL",
        dataset_version_id=corpus.dataset_version_id,
        prompt_tier=2,
    )
    ids = {row.case_id for row in remaining}
    assert first in ids
    assert second in ids


def test_find_cases_needing_extraction_skips_tier2_disabled_states(
    db_session: Session,
    seed: SeedFn,
) -> None:
    corpus = seed(
        "EXTRACTION_PERSISTENCE_FIND_TIER2_DISABLED",
        [_case_for_state("xp-find-ut", "UT"), _case_for_state("xp-find-md", "MD")],
    )
    ut_case_id = corpus.case_ids["xp-find-ut"]
    md_case_id = corpus.case_ids["xp-find-md"]

    tier2_remaining = find_cases_needing_extraction(
        db_session,
        prompt_hash="TESTHASH",
        model_id="TEST_MODEL",
        dataset_version_id=corpus.dataset_version_id,
        prompt_tier=2,
    )
    tier2_ids = {row.case_id for row in tier2_remaining}
    # UT is in TIER2_DISABLED_STATES (full source demographics); Tier-2 skips.
    assert ut_case_id not in tier2_ids
    assert md_case_id in tier2_ids

    tier1_remaining = find_cases_needing_extraction(
        db_session,
        prompt_hash="TESTHASH",
        model_id="TEST_MODEL",
        dataset_version_id=corpus.dataset_version_id,
        prompt_tier=1,
    )
    tier1_ids = {row.case_id for row in tier1_remaining}
    assert ut_case_id in tier1_ids
    assert md_case_id in tier1_ids


def test_bad_weapon_rejected_by_check_constraint(db_session: Session, seed: SeedFn) -> None:
    corpus = seed("EXTRACTION_PERSISTENCE_BAD_WEAPON", [_case("xp-bad")])
    case_id = corpus.case_ids["xp-bad"]

    with pytest.raises(Exception, match="case_extractions_weapon_check|check constraint"):
        db_session.execute(
            text(
                "INSERT INTO cold_case.case_extractions "
                "(case_id, extractor_version, prompt_hash, model_id, weapon) "
                "VALUES (:case_id, 'TEST_BAD', 'h', 'm', 'BAD_VALUE')"
            ),
            {"case_id": case_id},
        )
        db_session.commit()

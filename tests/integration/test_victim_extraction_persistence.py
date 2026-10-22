"""Integration tests for insert_victim_extractions against a real DB."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.extraction.cold_case.persistence import insert_victim_extractions
from casesignal.extraction.cold_case.tier2_extract_case import (
    CaseTier2Extraction,
    Tier2Field,
    Tier2Victim,
)
from tests.integration._seed import CaseSpec, SeedFn

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


_NULL_FIELD = Tier2Field(
    value=None,
    raw_phrase=None,
    source_start=None,
    source_end=None,
    low_confidence=False,
)


def _make_extraction(case_id: int) -> CaseTier2Extraction:
    """Build a CaseTier2Extraction with a 2-victim roster."""
    victim1 = Tier2Victim(
        ordinal=1,
        name=Tier2Field(
            value="Jane Doe",
            raw_phrase="Jane Doe",
            source_start=0,
            source_end=8,
            low_confidence=False,
        ),
        victim_age=Tier2Field(
            value=34,
            raw_phrase="34-year-old",
            source_start=9,
            source_end=20,
            low_confidence=False,
        ),
        victim_gender=Tier2Field(
            value="F",
            raw_phrase="she",
            source_start=21,
            source_end=24,
            low_confidence=False,
        ),
    )
    victim2 = Tier2Victim(
        ordinal=2,
        name=Tier2Field(
            value="John Smith",
            raw_phrase="John Smith",
            source_start=30,
            source_end=40,
            low_confidence=False,
        ),
        victim_age=Tier2Field(
            value=52,
            raw_phrase="52",
            source_start=41,
            source_end=43,
            low_confidence=False,
        ),
        victim_gender=Tier2Field(
            value="M",
            raw_phrase="he",
            source_start=44,
            source_end=46,
            low_confidence=False,
        ),
    )
    return CaseTier2Extraction(
        case_id=case_id,
        incident_date=_NULL_FIELD,
        address=_NULL_FIELD,
        victim_age=_NULL_FIELD,
        victim_gender=_NULL_FIELD,
        extractor_version="test-tier2-v0",
        prompt_hash="VEPERSIST_HASH",
        model_id="test-model",
        raw_llm_response=None,
        prompt_tokens=None,
        completion_tokens=None,
        cost_usd=None,
        notes=None,
        victims=(victim1, victim2),
    )


def test_insert_victim_extractions_writes_two_rows(
    db_session: Session, seed: SeedFn
) -> None:
    corpus = seed(
        "VE_PERSIST_INSERT",
        [
            CaseSpec(
                source_case_id="ve-insert",
                case_name="Victim Extraction Persistence Insert",
                state="ZZ",
                about_text="Jane Doe 34-year-old she John Smith 52 he",
            )
        ],
    )
    case_id = corpus.case_ids["ve-insert"]

    extraction = _make_extraction(case_id)
    insert_victim_extractions(db_session, extraction)
    db_session.commit()

    rows = (
        db_session.execute(
            text(
                "SELECT victim_ordinal, name_text, victim_age_text, victim_gender_text "
                "  FROM cold_case.victim_extraction "
                " WHERE case_id = :cid AND prompt_hash = :ph "
                " ORDER BY victim_ordinal"
            ),
            {"cid": case_id, "ph": "VEPERSIST_HASH"},
        )
        .mappings()
        .all()
    )

    assert len(rows) == 2

    assert rows[0]["victim_ordinal"] == 1
    assert rows[0]["name_text"] == "Jane Doe"
    assert rows[0]["victim_age_text"] == "34"
    assert rows[0]["victim_gender_text"] == "F"

    assert rows[1]["victim_ordinal"] == 2
    assert rows[1]["name_text"] == "John Smith"
    assert rows[1]["victim_age_text"] == "52"
    assert rows[1]["victim_gender_text"] == "M"


def test_insert_victim_extractions_idempotent(
    db_session: Session, seed: SeedFn
) -> None:
    corpus = seed(
        "VE_PERSIST_IDEMPOTENT",
        [
            CaseSpec(
                source_case_id="ve-idempotent",
                case_name="Victim Extraction Persistence Idempotent",
                state="ZZ",
                about_text="Jane Doe 34-year-old she John Smith 52 he",
            )
        ],
    )
    case_id = corpus.case_ids["ve-idempotent"]

    extraction = _make_extraction(case_id)

    # First insert
    insert_victim_extractions(db_session, extraction)
    db_session.commit()

    # Second insert — ON CONFLICT DO NOTHING must keep exactly 2 rows
    insert_victim_extractions(db_session, extraction)
    db_session.commit()

    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM cold_case.victim_extraction "
            "WHERE case_id = :cid AND prompt_hash = :ph"
        ),
        {"cid": case_id, "ph": "VEPERSIST_HASH"},
    ).scalar_one()

    assert count == 2

"""Tier-2 backfill behavior on cold_case.cases.

The Tier-2 prompt v3 extracts incident_date, address, victim_age, and
victim_gender. The ``backfill_canonical_values_from_tier2`` helper writes
the date and address back into the canonical cases row (when those columns
are NULL) and tags ``*_source='tier2'``. Victim demographics are never
backfilled.

Race extraction was removed in v3 — see feedback-no-llm-race-inference.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.extraction.cold_case.persistence import (
    backfill_canonical_values_from_tier2,
)
from casesignal.extraction.cold_case.tier2_extract_case import (
    CaseTier2Extraction,
    Tier2Field,
)
from tests.integration._seed import CaseSpec, SeedFn, VictimSpec

pytestmark = pytest.mark.integration


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    engine = create_engine(db_url)
    return sessionmaker(bind=engine)


def _null_field() -> Tier2Field:
    return Tier2Field(
        value=None, raw_phrase=None, source_start=None, source_end=None, low_confidence=False
    )


def _seed_temp_case(seed: SeedFn, source_case_id: str, race: str | None = None) -> int:
    """Insert a temp case + victim row for testing. Returns case_id."""
    corpus = seed(
        f"PHASE15_{source_case_id.upper()}",
        [
            CaseSpec(
                source_case_id=source_case_id,
                case_name="Test Victim",
                case_type="homicide",
                state="MD",
                about_text="narr",
                victims=[VictimSpec(first_name="Test", last_name="Victim", race=race)],
            )
        ],
    )
    return int(corpus.case_ids[source_case_id])


def test_backfill_sets_address_source_to_tier2(
    session_factory: sessionmaker[Session], seed: SeedFn
) -> None:
    """Backfill writes Tier-2 address into cases.address and tags it 'tier2'."""
    SF = session_factory
    with SF() as session:
        case_id = _seed_temp_case(seed, "test_p15_d")
        session.commit()
        session.execute(
            text("UPDATE cold_case.cases SET address=NULL, address_source=NULL WHERE case_id=:c"),
            {"c": case_id},
        )
        session.commit()

        extraction = CaseTier2Extraction(
            case_id=case_id,
            incident_date=_null_field(),
            address=Tier2Field(
                value="123 Main St",
                raw_phrase="123 Main St, Baltimore",
                source_start=0,
                source_end=22,
                low_confidence=False,
            ),
            victim_age=_null_field(),
            victim_gender=_null_field(),
            extractor_version="test",
            prompt_hash="x" * 64,
            model_id="test-model",
            raw_llm_response={},
            prompt_tokens=None,
            completion_tokens=None,
            cost_usd=None,
            notes=None,
        )
        backfill_canonical_values_from_tier2(session, extraction)
        session.commit()

        row = session.execute(
            text("SELECT address, address_source FROM cold_case.cases WHERE case_id=:c"),
            {"c": case_id},
        ).one()
        assert row.address == "123 Main St"
        assert row.address_source == "tier2"


def test_backfill_does_not_set_demographic_sources_to_tier2(
    session_factory: sessionmaker[Session], seed: SeedFn
) -> None:
    """Even when Tier-2 produces age/gender, ``backfill`` does NOT write them
    into the victim row. Demographics are case-level model outputs, not
    victim-identity-bound facts (writing them by case_id can pollute every
    victim row on multi-victim cases).
    """
    SF = session_factory
    with SF() as session:
        case_id = _seed_temp_case(seed, "test_p15_e")
        session.commit()
        session.execute(
            text(
                "UPDATE cold_case.victim SET gender=NULL, gender_source=NULL,"
                " age_text=NULL, age_source=NULL WHERE case_id=:c"
            ),
            {"c": case_id},
        )
        session.commit()

        extraction = CaseTier2Extraction(
            case_id=case_id,
            incident_date=_null_field(),
            address=_null_field(),
            victim_age=Tier2Field(
                value=25,
                raw_phrase="25 years old",
                source_start=10,
                source_end=22,
                low_confidence=False,
            ),
            victim_gender=Tier2Field(
                value="Female",
                raw_phrase="female",
                source_start=5,
                source_end=11,
                low_confidence=False,
            ),
            extractor_version="test",
            prompt_hash="x" * 64,
            model_id="test-model",
            raw_llm_response={},
            prompt_tokens=None,
            completion_tokens=None,
            cost_usd=None,
            notes=None,
        )
        backfill_canonical_values_from_tier2(session, extraction)
        session.commit()

        row = session.execute(
            text(
                "SELECT gender, gender_source, age_text, age_source"
                " FROM cold_case.victim WHERE case_id=:c LIMIT 1"
            ),
            {"c": case_id},
        ).one()
        assert row.gender is None
        assert row.gender_source is None
        assert row.age_text is None
        assert row.age_source is None

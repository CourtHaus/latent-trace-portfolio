"""Verify cold_case.cases.slug column properties (NOT NULL, unique, populated)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.integration._seed import CaseSpec, SeededCorpus, SeedFn

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    return seeded_corpus(
        "SLUG_SCHEMA_TEST",
        [
            CaseSpec(
                source_case_id="slug-a",
                case_name="Slug Schema Test",
                case_type="homicide",
                state="ZZ",
            )
        ],
    )


def test_slug_column_exists_not_null_unique(db_session: Session) -> None:
    info = db_session.execute(text("""
        SELECT column_name, is_nullable
          FROM information_schema.columns
         WHERE table_schema = 'cold_case'
           AND table_name = 'cases'
           AND column_name = 'slug'
    """)).one()
    assert info.is_nullable == "NO"


def test_backfill_populated_every_row(db_session: Session, corpus: SeededCorpus) -> None:
    null_count = db_session.execute(
        text("SELECT COUNT(*) FROM cold_case.cases WHERE slug IS NULL OR slug = ''")
    ).scalar()
    assert null_count == 0


def test_backfill_produces_unique_slugs(db_session: Session, corpus: SeededCorpus) -> None:
    total, distinct = db_session.execute(text("""
        SELECT COUNT(*) AS total, COUNT(DISTINCT slug) AS distinct
          FROM cold_case.cases
    """)).one()
    assert total == distinct


def test_unique_constraint_enforced(db_session: Session, corpus: SeededCorpus) -> None:
    existing_slug = db_session.execute(
        text("SELECT slug FROM cold_case.cases WHERE case_id = :case_id"),
        {"case_id": corpus.case_ids["slug-a"]},
    ).scalar_one()
    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("""
            INSERT INTO cold_case.cases (dataset_version_id, source_case_id, case_name, case_type, state, slug)
            VALUES (:dataset_version_id, 'slug-a-dup', 'Slug Schema Test Dup', 'homicide', 'ZZ', :slug)
        """),
            {"dataset_version_id": corpus.dataset_version_id, "slug": existing_slug},
        )
        db_session.commit()
    assert "uq_cases_slug" in str(exc.value) or "unique" in str(exc.value).lower()
    db_session.rollback()

"""normalize_dataset_values — the shared pipeline canonicalization stage.

Seeds a dataset with deliberately un-normalized categorical values and asserts
the stage canonicalizes case_type / gender / race, scoped to the dataset.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.services.normalize_dataset import normalize_dataset_values
from tests.integration._seed import CaseSpec, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_CASES = [
    CaseSpec(
        source_case_id="nz-01",
        case_name="Normalize One",
        state="QN",
        case_type="missing-person",
        victims=[VictimSpec(gender="male", race="black")],
    ),
    CaseSpec(
        source_case_id="nz-02",
        case_name="Normalize Two",
        state="QN",
        case_type="unidentified-person",
        victims=[VictimSpec(gender="female", race="WHITE")],
    ),
]


def _distinct(session: Session, sql: str, dv: int) -> set[str]:
    return {r[0] for r in session.execute(text(sql), {"dv": dv}).all()}


def test_stage_canonicalizes_scoped_to_dataset(seed: SeedFn, db_session: Session) -> None:
    corpus = seed("NORMALIZE_STAGE_TEST", _CASES)
    dv = corpus.dataset_version_id

    changed = normalize_dataset_values(db_session, dv)
    db_session.commit()

    # 2 case_type + 2 gender + 2 race rows were non-canonical.
    assert changed == 6

    assert _distinct(
        db_session,
        "SELECT DISTINCT case_type FROM cold_case.cases WHERE dataset_version_id = :dv",
        dv,
    ) == {"missing_person", "unidentified_person"}

    victim_sql = (
        "SELECT DISTINCT v.{col} FROM cold_case.victim v"
        " JOIN cold_case.cases c USING (case_id)"
        " WHERE c.dataset_version_id = :dv"
    )
    assert _distinct(db_session, victim_sql.format(col="gender"), dv) == {"M", "F"}
    assert _distinct(db_session, victim_sql.format(col="race"), dv) == {"Black", "White"}


def test_stage_is_idempotent(seed: SeedFn, db_session: Session) -> None:
    corpus = seed("NORMALIZE_STAGE_IDEMPOTENT", _CASES)
    dv = corpus.dataset_version_id

    normalize_dataset_values(db_session, dv)
    db_session.commit()

    # Second pass finds nothing left to change.
    assert normalize_dataset_values(db_session, dv) == 0

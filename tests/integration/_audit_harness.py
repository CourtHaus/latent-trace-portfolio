from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tests.integration._seed import CaseSpec, seed_corpus
from tools.audit.model import AuditContext

_RAW_PREFIX = "cold_case_fl_fdle"

# Mirrors src/casesignal/etl/adapters/cold_case_fl_fdle/raw_load.py DDL.
_RAW_DDL = """
CREATE TABLE {table} (
    dataset_version_id INTEGER NOT NULL,
    source_case_id     TEXT NOT NULL,
    case_title         TEXT,
    victim_name        TEXT,
    case_type          TEXT,
    incident_date      TEXT,
    incident_address   TEXT,
    incident_city      TEXT,
    reporting_agency   TEXT,
    agency_phone       TEXT,
    agency_address     TEXT,
    gender             TEXT,
    race               TEXT,
    height             TEXT,
    weight_lbs         INTEGER,
    dob                TEXT,
    narrative          TEXT,
    photos_json        TEXT,
    source_detail_url  TEXT NOT NULL,
    PRIMARY KEY (dataset_version_id, source_case_id)
)
"""

_RAW_COLS = [
    "dataset_version_id", "source_case_id", "case_title", "victim_name",
    "case_type", "incident_date", "incident_address", "incident_city",
    "reporting_agency", "agency_phone", "agency_address", "gender", "race", "height",
    "weight_lbs", "dob", "narrative", "photos_json", "source_detail_url",
]


@dataclass
class RawRow:
    source_case_id: str
    case_title: str | None = None
    victim_name: str | None = None
    case_type: str | None = "Homicide"
    incident_date: str | None = None
    incident_address: str | None = None
    incident_city: str | None = None
    reporting_agency: str | None = None
    agency_phone: str | None = None
    agency_address: str | None = None
    gender: str | None = None
    race: str | None = None
    height: str | None = None
    weight_lbs: int | None = None
    dob: str | None = None
    narrative: str | None = None
    photos_json: str | None = "[]"
    source_detail_url: str = "https://web.fdle.state.fl.us/unsolvedcases/public/caseDetails.jsf"


@contextmanager
def audit_corpus(
    session_factory: sessionmaker[Session],
    *,
    cases: list[CaseSpec],
    raw_rows: list[RawRow],
) -> Iterator[AuditContext]:
    """Seed a cold_case corpus + matching raw table, yield an AuditContext.

    `cases` and `raw_rows` should share source_case_ids so reconciliation rules
    line up. The raw table is named with the corpus's dataset_version_id so the
    audit's raw_table / dv resolution is exercised end to end.
    """
    corpus = seed_corpus(session_factory, source_code="AUDIT_TEST", cases=cases)
    dv = corpus.dataset_version_id
    table = f"raw_cold_case.{_RAW_PREFIX}_dv{dv}"
    cols = ", ".join(_RAW_COLS)
    params = ", ".join(f":{c}" for c in _RAW_COLS)
    row_cols = [c for c in _RAW_COLS if c != "dataset_version_id"]
    # The whole body is inside try/finally so a failure during raw-table setup
    # (DDL or INSERT) still drops any partially-created table and tears the
    # corpus down — otherwise a half-seeded run would leak rows into the DB.
    try:
        with session_factory() as s:
            s.execute(text(_RAW_DDL.format(table=table)))
            for row in raw_rows:
                values = {c: getattr(row, c) for c in row_cols}
                values["dataset_version_id"] = dv
                s.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), values)
            s.commit()
        yield AuditContext(
            source=_RAW_PREFIX,
            source_code="AUDIT_TEST",
            state="FL",
            dataset_version_id=dv,
            raw_table=table,
            total_cases=len(cases),
        )
    finally:
        with session_factory() as s:
            s.execute(text(f"DROP TABLE IF EXISTS {table}"))
            s.commit()
        corpus.teardown()

from typing import Any

from sqlalchemy import text

from casesignal.etl.services.db import create_session_factory
from tests.integration._audit_harness import RawRow, audit_corpus
from tests.integration._seed import CaseSpec


def test_harness_creates_aligned_raw_and_cold(db_engine: Any) -> None:
    sf = create_session_factory(db_engine)
    cases = [CaseSpec(source_case_id="X1", case_name="Test Case One", state="FL")]
    raws = [RawRow(source_case_id="X1", case_title="Test Case One")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            raw_n = s.execute(text(f"SELECT count(*) FROM {ctx.raw_table}")).scalar_one()
            cold_n = s.execute(
                text("SELECT count(*) FROM cold_case.cases WHERE dataset_version_id = :dv"),
                {"dv": ctx.dataset_version_id},
            ).scalar_one()
        assert raw_n == 1
        assert cold_n == 1
        assert ctx.state == "FL"

import os

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


def test_pg_trgm_extension_present() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        installed = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        ).first()
        assert installed is not None


def test_trgm_indexes_present() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    expected = {
        "idx_cases_case_name_trgm",
        "idx_cases_source_case_id_trgm",
        "idx_victim_first_name_trgm",
        "idx_victim_last_name_trgm",
    }
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE indexname = ANY(:names)"),
            {"names": list(expected)},
        ).all()
        found = {r[0] for r in rows}
        assert found == expected

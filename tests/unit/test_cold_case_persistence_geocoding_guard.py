"""enqueue_geocoding_job_from_tier2 — precision-guard branches."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from casesignal.extraction.cold_case.persistence import (
    enqueue_geocoding_job_from_tier2,
)
from casesignal.extraction.cold_case.tier2_extract_case import (
    CaseTier2Extraction,
    Tier2Field,
)


def _make_tier2(case_id: int, address: str | None = "1 Main St") -> CaseTier2Extraction:
    return CaseTier2Extraction(
        case_id=case_id,
        extractor_version="test",
        prompt_hash="h",
        model_id="m",
        raw_llm_response=None,
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        notes=None,
        incident_date=Tier2Field(None, None, None, None, False),
        address=Tier2Field(address, address, 0, len(address) if address else 0, False),
        victim_age=Tier2Field(None, None, None, None, False),
        victim_gender=Tier2Field(None, None, None, None, False),
    )


def _fake_session_with_precision(precision: str | None) -> MagicMock:
    session = MagicMock()
    row = MagicMock()
    row.geocode_precision = precision
    cursor = MagicMock()
    cursor.first.return_value = row
    session.execute.return_value = cursor
    return session


@pytest.mark.parametrize("precision", [None, "failed", "county"])
def test_enqueues_when_precision_is_null_failed_or_county(precision: Any) -> None:
    session = _fake_session_with_precision(precision)
    enqueue_geocoding_job_from_tier2(
        session, _make_tier2(case_id=1), state_code="MD", county_fips="24005"
    )
    # SELECT + INSERT = 2 execute calls
    assert session.execute.call_count == 2


@pytest.mark.parametrize("precision", ["street", "landmark", "zip"])
def test_skips_when_precision_is_already_good(precision: Any) -> None:
    session = _fake_session_with_precision(precision)
    enqueue_geocoding_job_from_tier2(
        session, _make_tier2(case_id=1), state_code="MD", county_fips="24005"
    )
    # Only the precision-check SELECT; no INSERT
    assert session.execute.call_count == 1


def test_skips_when_address_is_null() -> None:
    session = MagicMock()
    enqueue_geocoding_job_from_tier2(
        session,
        _make_tier2(case_id=1, address=None),
        state_code="MD",
        county_fips="24005",
    )
    # No DB calls at all when address is empty
    assert session.execute.call_count == 0

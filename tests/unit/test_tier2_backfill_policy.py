from __future__ import annotations

from typing import Any

from casesignal.extraction.cold_case.persistence import backfill_canonical_values_from_tier2
from casesignal.extraction.cold_case.tier2_extract_case import (
    CaseTier2Extraction,
    Tier2Field,
)


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[dict[str, Any] | None] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> None:
        self.statements.append(str(statement))
        self.params.append(params)


def _field(value: Any, *, low_confidence: bool = False) -> Tier2Field:
    return Tier2Field(
        value=value,
        raw_phrase=str(value) if value is not None else None,
        source_start=0 if value is not None else None,
        source_end=len(str(value)) if value is not None else None,
        low_confidence=low_confidence,
    )


def _tier2_extraction() -> CaseTier2Extraction:
    return CaseTier2Extraction(
        case_id=123,
        incident_date=_field("2001-02-03"),
        address=_field("100 Main St"),
        victim_age=_field(25),
        victim_gender=_field("F"),
        extractor_version="test",
        prompt_hash="x" * 64,
        model_id="test-model",
        raw_llm_response={},
        prompt_tokens=None,
        completion_tokens=None,
        cost_usd=None,
        notes=None,
    )


def test_tier2_backfill_does_not_write_victim_demographics() -> None:
    session = RecordingSession()

    backfill_canonical_values_from_tier2(session, _tier2_extraction())  # type: ignore[arg-type]

    joined_sql = "\n".join(session.statements)
    assert "UPDATE cold_case.cases" in joined_sql
    assert "SET incident_date" in joined_sql
    assert "SET address" in joined_sql
    assert "UPDATE cold_case.victim" not in joined_sql

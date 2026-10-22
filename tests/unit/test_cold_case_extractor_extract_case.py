"""Unit tests for extract_case() — the core extractor function.

Tests use a fake LLMClient that returns pre-programmed responses so
extraction logic is exercised without real API calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from casesignal.extraction.cold_case.extract_case import (
    EXTRACTOR_VERSION,
    extract_case,
)
from casesignal.worker.llm.protocol import LLMMessage, LLMTurn, ToolCall


def _fake_llm_turn(
    weapon: str, weapon_phrase: str | None, location_type: str, location_type_phrase: str | None
) -> LLMTurn:
    """Build an LLMTurn that returns the extraction as a tool call."""
    args = {
        "weapon": weapon,
        "weapon_phrase": weapon_phrase,
        "location_type": location_type,
        "location_type_phrase": location_type_phrase,
    }
    tc = ToolCall(id="call_1", name="record_extraction", arguments=args)
    return LLMTurn(
        assistant_message=LLMMessage(role="assistant", content="", tool_calls=[tc]),
        finish_reason="tool_calls",
        malformed_reason=None,
    )


class FakeLLMClient:
    """Minimal LLMClient fake for testing. Not provider-specific."""

    def __init__(
        self, turn: LLMTurn, *, prompt_tokens: int = 100, completion_tokens: int = 50
    ) -> None:
        self.turn = turn
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls: list[list[LLMMessage]] = []

    def chat(self, messages: Any, tools: Any, max_tokens: Any = 2048) -> Any:
        self.calls.append(messages)
        return self.turn


ABOUT_TEXT_SHOT = "The victim was shot to death inside of her apartment."


def test_extract_case_populates_both_fields_on_success() -> None:
    llm = FakeLLMClient(
        _fake_llm_turn(
            "firearm",
            "shot to death",
            "residence",
            "inside of her apartment",
        )
    )

    result = extract_case(
        case_id=42,
        about_text=ABOUT_TEXT_SHOT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="gpt-4o-mini-2024-07-18",
    )

    assert result.case_id == 42
    assert result.weapon.value == "firearm"
    assert result.weapon.raw_phrase == "shot to death"
    assert result.weapon.source_start == ABOUT_TEXT_SHOT.find("shot to death")
    assert result.weapon.low_confidence is False

    assert result.location_type.value == "residence"
    assert result.location_type.raw_phrase == "inside of her apartment"
    assert result.location_type.source_start == ABOUT_TEXT_SHOT.find("inside of her apartment")
    assert result.location_type.low_confidence is False

    assert result.model_id == "gpt-4o-mini-2024-07-18"
    assert result.extractor_version == EXTRACTOR_VERSION
    assert result.raw_llm_response is not None


def test_extract_case_unresolved_phrase_marks_low_confidence() -> None:
    """LLM returns value but paraphrased phrase → low_confidence=True, value preserved."""
    llm = FakeLLMClient(
        _fake_llm_turn(
            "firearm",
            "shot fatally",  # paraphrase; not in text verbatim
            "residence",
            "inside of her apartment",
        )
    )

    result = extract_case(
        case_id=42,
        about_text=ABOUT_TEXT_SHOT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="gpt-4o-mini-2024-07-18",
    )

    assert result.weapon.value == "firearm"  # classification preserved
    assert result.weapon.low_confidence is True
    assert result.weapon.source_start is None
    assert result.weapon.source_end is None

    assert result.location_type.low_confidence is False


def test_extract_case_unknown_classification_has_null_phrase() -> None:
    """LLM says unknown → phrase is null → not a low_confidence drop."""
    llm = FakeLLMClient(
        _fake_llm_turn(
            "unknown",
            None,
            "residence",
            "inside of her apartment",
        )
    )

    result = extract_case(
        case_id=42,
        about_text=ABOUT_TEXT_SHOT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="gpt-4o-mini-2024-07-18",
    )

    assert result.weapon.value == "unknown"
    assert result.weapon.raw_phrase is None
    # unknown + null phrase is NOT low_confidence — it's a valid "don't know".
    assert result.weapon.low_confidence is False
    assert result.weapon.source_start is None
    assert result.weapon.source_end is None


def test_extract_case_propagates_llm_exception() -> None:
    """LLM API failure must propagate — the queue handler turns it into job
    status='failed'. Swallowing it as a 'succeeded' extraction with marker
    fields masked the gpt-4.1-mini-vs-gpt-4o-mini 404 across 2,796 OH jobs
    in Phase 5 (see PR #73). Real correctness bug — keep this test.
    """
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("LLM API timeout")

    with pytest.raises(RuntimeError, match="LLM API timeout"):
        extract_case(
            case_id=42,
            about_text=ABOUT_TEXT_SHOT,
            llm_client=llm,
            prompt_template="prompt {about_text}",
            model_id="gpt-4o-mini-2024-07-18",
        )


def test_extract_case_handles_malformed_llm_response() -> None:
    """LLM returns no tool call → entire extraction fails with notes."""
    malformed_turn = LLMTurn(
        assistant_message=LLMMessage(role="assistant", content="I don't know."),
        finish_reason="malformed",
        malformed_reason="expected tool_calls but got content",
    )
    llm = FakeLLMClient(malformed_turn)

    result = extract_case(
        case_id=42,
        about_text=ABOUT_TEXT_SHOT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="gpt-4o-mini-2024-07-18",
    )

    assert result.weapon.value is None
    assert result.location_type.value is None
    assert result.notes is not None

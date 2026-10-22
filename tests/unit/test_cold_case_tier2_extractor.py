"""Tier-2 extractor — incident_date / address / victim_age / victim_gender."""

from __future__ import annotations

from typing import Any

import pytest

from casesignal.extraction.cold_case.tier2_extract_case import (
    EXTRACTOR_VERSION,
    extract_case_tier2,
)
from casesignal.worker.llm.protocol import LLMMessage, LLMTurn, ToolCall, ToolSchema


def _fake_tier2_turn(
    *,
    incident_date: str | None,
    incident_date_phrase: str | None,
    address: str | None,
    address_phrase: str | None,
    victim_age: int | None,
    victim_age_phrase: str | None,
    victim_gender: str | None,
    victim_gender_phrase: str | None,
) -> LLMTurn:
    # Build a single-victim roster entry so back-compat scalar fields are
    # populated from roster[0]. This mirrors the new LLM schema (Task 2+3).
    victims = (
        [
            {
                "name": None,
                "name_phrase": None,
                "age": victim_age,
                "age_phrase": victim_age_phrase,
                "gender": victim_gender,
                "gender_phrase": victim_gender_phrase,
            }
        ]
        if (victim_age is not None or victim_gender is not None)
        else []
    )
    args = {
        "incident_date": incident_date,
        "incident_date_phrase": incident_date_phrase,
        "address": address,
        "address_phrase": address_phrase,
        "victims": victims,
    }
    tc = ToolCall(id="call_1", name="record_tier2_extraction", arguments=args)
    return LLMTurn(
        assistant_message=LLMMessage(role="assistant", content="", tool_calls=[tc]),
        finish_reason="tool_calls",
        malformed_reason=None,
    )


class FakeLLMClient:
    def __init__(self, turn: LLMTurn) -> None:
        self.turn = turn

    def chat(self, messages: Any, tools: Any, max_tokens: Any = 2048) -> Any:
        return self.turn


# Invented narrative with literal spans for deterministic provenance tests.
ABOUT_TEXT = (
    "On January 1, 2000, a report described an incident at the "
    "1000 block of Example Road, 00000. The 31-year-old Casey Exampleton "
    "was named in the report, which recorded his age."
)


def test_full_success_populates_all_four_fields() -> None:
    llm = FakeLLMClient(
        _fake_tier2_turn(
            incident_date="2000-01-01",
            incident_date_phrase="January 1, 2000",
            address="1000 block of Example Road, 00000",
            address_phrase="1000 block of Example Road, 00000",
            victim_age=31,
            victim_age_phrase="31-year-old",
            victim_gender="M",
            victim_gender_phrase="his",
        )
    )

    result = extract_case_tier2(
        case_id=42,
        about_text=ABOUT_TEXT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    assert result.case_id == 42
    assert result.extractor_version == EXTRACTOR_VERSION

    assert result.incident_date.value == "2000-01-01"
    assert result.incident_date.raw_phrase == "January 1, 2000"
    assert result.incident_date.source_start == ABOUT_TEXT.find("January 1, 2000")
    assert result.incident_date.low_confidence is False

    assert result.address.value == "1000 block of Example Road, 00000"
    assert result.address.low_confidence is False

    assert result.victim_age.value == 31
    assert result.victim_age.raw_phrase == "31-year-old"
    assert result.victim_age.source_start == ABOUT_TEXT.find("31-year-old")
    assert result.victim_age.low_confidence is False

    assert result.victim_gender.value == "M"
    assert result.victim_gender.raw_phrase == "his"
    assert result.victim_gender.low_confidence is False


def test_null_fields_pass_through_as_non_low_conf() -> None:
    """Tier-2 represents 'not stated' as null with low_confidence=False."""
    llm = FakeLLMClient(
        _fake_tier2_turn(
            incident_date=None,
            incident_date_phrase=None,
            address=None,
            address_phrase=None,
            victim_age=None,
            victim_age_phrase=None,
            victim_gender=None,
            victim_gender_phrase=None,
        )
    )

    result = extract_case_tier2(
        case_id=1,
        about_text="brief narrative without identifying info",
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    for field in (
        result.incident_date,
        result.address,
        result.victim_age,
        result.victim_gender,
    ):
        assert field.value is None
        assert field.low_confidence is False


def test_unresolved_phrase_marks_low_confidence() -> None:
    """Phrase doesn't appear verbatim → low_confidence, value preserved."""
    llm = FakeLLMClient(
        _fake_tier2_turn(
            incident_date="2000-01-01",
            incident_date_phrase="paraphrased date wording",  # not in narrative
            address=None,
            address_phrase=None,
            victim_age=None,
            victim_age_phrase=None,
            victim_gender=None,
            victim_gender_phrase=None,
        )
    )

    result = extract_case_tier2(
        case_id=1,
        about_text=ABOUT_TEXT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    assert result.incident_date.value == "2000-01-01"  # preserved
    assert result.incident_date.low_confidence is True
    assert result.incident_date.source_start is None


def test_invalid_age_becomes_low_confidence_null() -> None:
    llm = FakeLLMClient(
        _fake_tier2_turn(
            incident_date=None,
            incident_date_phrase=None,
            address=None,
            address_phrase=None,
            victim_age=200,  # nonsense
            victim_age_phrase="200-year-old",
            victim_gender=None,
            victim_gender_phrase=None,
        )
    )

    result = extract_case_tier2(
        case_id=1,
        about_text="anything",
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    assert result.victim_age.value is None
    assert result.victim_age.low_confidence is True


def test_invalid_gender_value_becomes_low_confidence() -> None:
    llm = FakeLLMClient(
        _fake_tier2_turn(
            incident_date=None,
            incident_date_phrase=None,
            address=None,
            address_phrase=None,
            victim_age=None,
            victim_age_phrase=None,
            victim_gender="X",  # not in {M, F}
            victim_gender_phrase="something",
        )
    )

    result = extract_case_tier2(
        case_id=1,
        about_text="anything",
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    assert result.victim_gender.value is None
    assert result.victim_gender.low_confidence is True


def test_dict_shaped_scalar_value_does_not_crash() -> None:
    """Qwen has been observed returning {"value": "M"} for victim_gender
    (and similar nested shapes for other scalar fields). Pre-fix this
    raised `TypeError: unhashable type: 'dict'` in _build_gender_field.
    Now the coerce treats non-scalar input as None.
    """
    args = {
        "incident_date": {"unexpected": "shape"},
        "incident_date_phrase": None,
        "address": ["a", "list"],
        "address_phrase": None,
        "victim_age": {"value": 30},
        "victim_age_phrase": None,
        "victim_gender": {"value": "M"},
        "victim_gender_phrase": None,
    }
    tc = ToolCall(id="call_1", name="record_tier2_extraction", arguments=args)
    turn = LLMTurn(
        assistant_message=LLMMessage(role="assistant", content="", tool_calls=[tc]),
        finish_reason="tool_calls",
        malformed_reason=None,
    )
    llm = FakeLLMClient(turn)

    result = extract_case_tier2(
        case_id=1,
        about_text="anything",
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    # All non-scalar inputs coerce to None — no crash, no garbage values.
    assert result.incident_date.value is None
    assert result.address.value is None
    assert result.victim_age.value is None
    assert result.victim_gender.value is None


def test_llm_exception_propagates() -> None:
    """Tier-2 LLM API failure must propagate — the queue handler turns it
    into job status='failed'. See PR #73 / OH AG Phase 5 incident.
    """

    class _BoomClient:
        def chat(
            self,
            messages: list[LLMMessage],
            tools: list[ToolSchema],
            max_tokens: int = 2048,
        ) -> LLMTurn:
            raise RuntimeError("connection died")

    with pytest.raises(RuntimeError, match="connection died"):
        extract_case_tier2(
            case_id=99,
            about_text="anything",
            llm_client=_BoomClient(),
            prompt_template="prompt {about_text}",
            model_id="qwen2.5:7b",
        )


def test_content_json_fallback_accepts_partial_dict_per_pr_124() -> None:
    """Content JSON missing some expected keys is intentionally accepted.

    PR #124 dropped a stricter ``_REQUIRED_KEYS.issubset`` check on the
    content-fallback path so that local models (qwen3, deepseek-r1) that
    occasionally emit partial JSON don't crash the extractor. Missing keys
    become null/low-confidence downstream rather than a malformed-extraction
    failure. This test pins the intentional looser-parse contract — if a
    future change re-introduces a strict key check, this test will catch it.
    """
    # Only 2 of 8 keys present; rest must default to null.
    partial_content = (
        '{"incident_date": "2000-01-01",'
        ' "incident_date_phrase": "January 1, 2000"}'
    )
    llm = FakeLLMClient(
        LLMTurn(
            assistant_message=LLMMessage(role="assistant", content=partial_content, tool_calls=[]),
            finish_reason="stop",
            malformed_reason=None,
        )
    )

    result = extract_case_tier2(
        case_id=1,
        about_text=ABOUT_TEXT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    # Present keys flow through.
    assert result.incident_date.value == "2000-01-01"
    # Absent keys gracefully degrade to null + low_confidence.
    assert result.address.value is None
    assert result.victim_age.value is None
    assert result.victim_gender.value is None


def test_content_json_fallback_when_no_tool_calls() -> None:
    """Local models that emit JSON in content instead of tool-call."""
    content_json = (
        '{"incident_date": "2000-01-01",'
        ' "incident_date_phrase": "January 1, 2000",'
        ' "address": null,'
        ' "address_phrase": null,'
        ' "victims": [{"name": null, "name_phrase": null,'
        '              "age": 31, "age_phrase": "31-year-old",'
        '              "gender": "M", "gender_phrase": "his"}]}'
    )
    llm = FakeLLMClient(
        LLMTurn(
            assistant_message=LLMMessage(role="assistant", content=content_json, tool_calls=[]),
            finish_reason="stop",
            malformed_reason=None,
        )
    )

    result = extract_case_tier2(
        case_id=1,
        about_text=ABOUT_TEXT,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )

    assert result.incident_date.value == "2000-01-01"
    # Single-victim roster → back-compat scalars populated from roster[0].
    assert result.victim_age.value == 31
    assert result.victim_gender.value == "M"

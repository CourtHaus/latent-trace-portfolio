"""Tests for _build_victim_roster and the back-compat scalar wiring in extract_case_tier2."""

from __future__ import annotations

from typing import Any

from casesignal.extraction.cold_case.tier2_extract_case import _build_victim_roster
from casesignal.worker.llm.protocol import LLMMessage, LLMTurn, ToolCall

NARR = (
    "This invented narrative names Alex Exampleton, a 23 year old male, "
    "and Robin Sampleton, a 21 year old male."
)


# ---------------------------------------------------------------------------
# _build_victim_roster unit tests
# ---------------------------------------------------------------------------

def test_roster_two_victims_parsed() -> None:
    arg = [
        {"name": "Alex Exampleton", "name_phrase": "Alex Exampleton", "age": 23,
         "age_phrase": "23 year old", "gender": "M", "gender_phrase": "male"},
        {"name": "Robin Sampleton", "name_phrase": "Robin Sampleton", "age": 21,
         "age_phrase": "21 year old", "gender": "M", "gender_phrase": "male"},
    ]
    roster = _build_victim_roster(arg, NARR)
    assert len(roster) == 2
    assert roster[0].ordinal == 1 and roster[0].name.value == "Alex Exampleton"
    assert roster[0].victim_age.value == 23
    assert roster[1].name.value == "Robin Sampleton"
    assert roster[1].ordinal == 2


def test_roster_empty_or_missing_is_empty_tuple() -> None:
    assert _build_victim_roster(None, NARR) == ()
    assert _build_victim_roster([], NARR) == ()


def test_roster_reuses_existing_field_builders() -> None:
    arg = [{"name": "X", "name_phrase": "X", "age": 999, "age_phrase": "999",
            "gender": "Z", "gender_phrase": "?"}]
    roster = _build_victim_roster(arg, "X was found")
    assert roster[0].victim_age.value is None and roster[0].victim_age.low_confidence
    assert roster[0].victim_gender.value is None  # "Z" not in _GENDER_VALUES


def test_roster_non_dict_entries_skipped_ordinals_contiguous() -> None:
    """Non-dict entries are skipped; kept victims get contiguous 1..N ordinals."""
    arg = [
        {"name": "Alice", "name_phrase": "Alice", "age": 30,
         "age_phrase": "30 year old", "gender": "F", "gender_phrase": "her"},
        "bad_entry",  # not a dict — must be skipped
        {"name": "Bob", "name_phrase": "Bob", "age": 25,
         "age_phrase": "25 year old", "gender": "M", "gender_phrase": "his"},
    ]
    roster = _build_victim_roster(arg, "Alice was 30 and Bob was 25")
    assert len(roster) == 2
    assert roster[0].ordinal == 1
    assert roster[1].ordinal == 2  # contiguous — not 3


# ---------------------------------------------------------------------------
# Back-compat scalar derivation via extract_case_tier2
# ---------------------------------------------------------------------------

from casesignal.extraction.cold_case.tier2_extract_case import extract_case_tier2


def _roster_turn(victims_list: list[dict[str, Any]]) -> LLMTurn:
    """Build an LLMTurn with a victims array and null date/address."""
    args = {
        "incident_date": None,
        "incident_date_phrase": None,
        "address": None,
        "address_phrase": None,
        "victims": victims_list,
    }
    tc = ToolCall(id="call_1", name="record_tier2_extraction", arguments=args)
    return LLMTurn(
        assistant_message=LLMMessage(role="assistant", content="", tool_calls=[tc]),
        finish_reason="tool_calls",
        malformed_reason=None,
    )


class _FakeLLM:
    def __init__(self, turn: LLMTurn) -> None:
        self.turn = turn

    def chat(self, messages: Any, tools: Any, max_tokens: Any = 2048) -> Any:
        return self.turn


SINGLE_VICTIM_NARR = (
    "In this invented example, Casey Exampleton is a 31-year-old person. His age is recorded."
)


def test_single_victim_roster_populates_scalar_fields() -> None:
    """Single-victim roster → scalar victim_age/victim_gender come from roster[0]."""
    llm = _FakeLLM(
        _roster_turn([
            {"name": "Casey Exampleton", "name_phrase": "Casey Exampleton",
             "age": 31, "age_phrase": "31-year-old",
             "gender": "M", "gender_phrase": "His"},
        ])
    )
    result = extract_case_tier2(
        case_id=99,
        about_text=SINGLE_VICTIM_NARR,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )
    assert result.victim_age.value == 31
    assert result.victim_gender.value == "M"
    assert len(result.victims) == 1
    assert result.victims[0].name.value == "Casey Exampleton"


def test_two_victim_roster_nulls_scalar_fields() -> None:
    """Multi-victim roster → scalar victim_age/victim_gender must be null (non-low-conf)."""
    llm = _FakeLLM(
        _roster_turn([
            {"name": "Alex Exampleton", "name_phrase": "Alex Exampleton",
             "age": 23, "age_phrase": "23 year old",
             "gender": "M", "gender_phrase": "male"},
            {"name": "Robin Sampleton", "name_phrase": "Robin Sampleton",
             "age": 21, "age_phrase": "21 year old",
             "gender": "M", "gender_phrase": "male"},
        ])
    )
    result = extract_case_tier2(
        case_id=7,
        about_text=NARR,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )
    assert result.victim_age.value is None
    assert result.victim_age.low_confidence is False
    assert result.victim_gender.value is None
    assert result.victim_gender.low_confidence is False
    assert len(result.victims) == 2


def test_empty_victim_roster_nulls_scalar_fields() -> None:
    """Empty roster → scalar fields null (non-low-conf), victims tuple empty."""
    llm = _FakeLLM(_roster_turn([]))
    result = extract_case_tier2(
        case_id=5,
        about_text="Brief narrative.",
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )
    assert result.victim_age.value is None
    assert result.victim_age.low_confidence is False
    assert result.victims == ()


def test_roster_dict_shaped_fields_do_not_crash() -> None:
    """Qwen occasionally emits dicts for scalar fields inside a victims entry
    (e.g. {"value": "M"} for gender). _coerce_scalar inside _build_victim_roster
    must convert these to None rather than passing a dict into the field builders,
    which would raise TypeError (dict not in set / int(dict))."""
    arg = [
        {
            "name": {"value": "Jane Doe"},
            "name_phrase": None,
            "age": {"value": 30},
            "age_phrase": None,
            "gender": {"value": "M"},
            "gender_phrase": None,
        }
    ]
    roster = _build_victim_roster(arg, "Jane Doe age 30")
    assert len(roster) == 1
    assert roster[0].name.value is None
    assert roster[0].victim_age.value is None
    assert roster[0].victim_gender.value is None
    assert roster[0].victim_age.low_confidence is False
    assert roster[0].victim_gender.low_confidence is False


# ---------------------------------------------------------------------------
# v3 scalar fallback (worker still on old prompt — no "victims" key in args)
# ---------------------------------------------------------------------------

V3_NARR = (
    "On March 5, 1995, a 42-year-old woman was found deceased. She had been shot."
)


def _v3_turn(
    victim_age: int | None,
    victim_age_phrase: str | None,
    victim_gender: str | None,
    victim_gender_phrase: str | None,
) -> LLMTurn:
    """Build an LLMTurn with v3-style scalar keys — NO 'victims' key at all."""
    args: dict[str, Any] = {
        "incident_date": None,
        "incident_date_phrase": None,
        "address": None,
        "address_phrase": None,
        # Intentionally absent: "victims"
        "victim_age": victim_age,
        "victim_age_phrase": victim_age_phrase,
        "victim_gender": victim_gender,
        "victim_gender_phrase": victim_gender_phrase,
    }
    tc = ToolCall(id="call_v3", name="record_tier2_extraction", arguments=args)
    return LLMTurn(
        assistant_message=LLMMessage(role="assistant", content="", tool_calls=[tc]),
        finish_reason="tool_calls",
        malformed_reason=None,
    )


def test_v3_args_populate_scalar_fields_and_roster() -> None:
    """v3 response (scalar keys, no 'victims' key) → scalar fields are populated
    AND a single-element roster is synthesised so downstream roster code works."""
    llm = _FakeLLM(_v3_turn(42, "42-year-old", "F", "She"))
    result = extract_case_tier2(
        case_id=77,
        about_text=V3_NARR,
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )
    # Scalar fields must be populated (restoring prior v3 behavior).
    assert result.victim_age.value == 42
    assert result.victim_gender.value == "F"
    # Roster must be non-empty (single entry) with name=None (v3 has no name).
    assert len(result.victims) == 1
    assert result.victims[0].ordinal == 1
    assert result.victims[0].name.value is None


def test_v4_empty_victims_list_does_not_trigger_v3_fallback() -> None:
    """v4 response with 'victims: []' → genuinely zero victims; scalars stay null.
    The fallback must NOT fire just because the list is empty — it must only
    fire when the key is absent entirely."""
    llm = _FakeLLM(_roster_turn([]))  # v4 shape: "victims" key present, value []
    result = extract_case_tier2(
        case_id=88,
        about_text="Brief narrative.",
        llm_client=llm,
        prompt_template="prompt {about_text}",
        model_id="qwen2.5:7b",
    )
    # v4 empty list → scalars null, roster empty tuple (no fallback).
    assert result.victim_age.value is None
    assert result.victim_age.low_confidence is False
    assert result.victims == ()

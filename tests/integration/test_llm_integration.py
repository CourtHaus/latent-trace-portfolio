"""Opt-in live-endpoint integration tests for the OpenAIClient adapter.

These tests hit a real OpenAI-compatible endpoint (Ollama by default) and
are skipped unless LLM_INTEGRATION=1 is set. They exist to catch regressions
in the adapter's wire-format handling that unit tests with mocks can't find.
"""

from __future__ import annotations

import json
import os

import pytest

from casesignal.worker.llm import LLMMessage, OpenAIClient, ToolSchema

requires_llm_integration = pytest.mark.skipif(
    os.environ.get("LLM_INTEGRATION") != "1",
    reason="Set LLM_INTEGRATION=1 to run live-endpoint tests",
)


def _build_client() -> OpenAIClient:
    return OpenAIClient(
        base_url=os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", "ollama"),
        model=os.environ.get("OPENAI_MODEL", "qwen2.5:7b"),
    )


@requires_llm_integration
def test_chat_returns_valid_turn_without_tools() -> None:
    client = _build_client()
    turn = client.chat(
        messages=[LLMMessage(role="user", content="Say exactly the word OK and stop.")],
        tools=[],
        max_tokens=32,
    )
    assert turn.finish_reason in ("stop", "length"), f"unexpected: {turn.finish_reason}"


@requires_llm_integration
def test_chat_with_tool_calls_it_or_answers_directly() -> None:
    client = _build_client()
    tool = ToolSchema(
        name="cold_case_search",
        description="Search cold-case records by state and incident-year range.",
        parameters={
            "type": "object",
            "properties": {
                "state": {"type": "string"},
                "year_min": {"type": "integer"},
                "year_max": {"type": "integer"},
            },
            "required": ["state", "year_min"],
        },
    )
    turn = client.chat(
        messages=[
            LLMMessage(role="system", content="Use the tool to fetch case data before answering."),
            LLMMessage(role="user", content="Find Virginia cold cases between 2010 and 2015."),
        ],
        tools=[tool],
        max_tokens=512,
    )
    # The model may call the tool or respond directly — either is a valid outcome.
    assert turn.finish_reason in ("stop", "tool_calls"), f"unexpected: {turn.finish_reason}"
    if turn.finish_reason == "tool_calls":
        assert len(turn.assistant_message.tool_calls) >= 1
        tc = turn.assistant_message.tool_calls[0]
        assert tc.name == "cold_case_search"
        assert "state" in tc.arguments
        assert "year_min" in tc.arguments


@requires_llm_integration
def test_chat_handles_tool_result_injection() -> None:
    """Prove a full request/response with a tool_result message injected round-trips cleanly."""
    client = _build_client()
    tool = ToolSchema(
        name="get_weather",
        description="Get weather for a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
    # First turn: expect the model to call the tool
    turn1 = client.chat(
        messages=[
            LLMMessage(role="system", content="Use the tool; do not answer from memory."),
            LLMMessage(role="user", content="What is the weather in Paris right now?"),
        ],
        tools=[tool],
        max_tokens=256,
    )
    if turn1.finish_reason != "tool_calls":
        pytest.skip(
            f"Model did not call the tool (finish_reason={turn1.finish_reason}); skipping round-trip"
        )
    tc = turn1.assistant_message.tool_calls[0]

    # Second turn: inject a tool result and expect a stop (or another tool_calls)
    turn2 = client.chat(
        messages=[
            LLMMessage(role="system", content="Use the tool; do not answer from memory."),
            LLMMessage(role="user", content="What is the weather in Paris right now?"),
            turn1.assistant_message,
            LLMMessage(
                role="tool",
                tool_call_id=tc.id,
                content=json.dumps({"city": "Paris", "temp_c": 18, "condition": "sunny"}),
            ),
        ],
        tools=[tool],
        max_tokens=256,
    )
    assert turn2.finish_reason in ("stop", "tool_calls")

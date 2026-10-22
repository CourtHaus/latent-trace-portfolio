"""Unit tests for LLM protocol dataclasses and __post_init__ invariants."""

from __future__ import annotations

import pytest

from casesignal.worker.llm.protocol import (
    LLMMessage,
    LLMTurn,
    ToolCall,
    ToolSchema,
)


def test_tool_schema_constructs() -> None:
    ts = ToolSchema(name="x", description="d", parameters={"type": "object"})
    assert ts.name == "x"


def test_tool_call_constructs() -> None:
    tc = ToolCall(id="call_1", name="t", arguments={"a": 1})
    assert tc.arguments == {"a": 1}


def test_assistant_message_with_content_is_valid() -> None:
    m = LLMMessage(role="assistant", content="hello")
    assert m.content == "hello"


def test_assistant_message_with_tool_calls_is_valid() -> None:
    tc = ToolCall(id="call_1", name="t", arguments={})
    m = LLMMessage(role="assistant", tool_calls=[tc])
    assert m.tool_calls[0].id == "call_1"


def test_assistant_message_with_neither_content_nor_tool_calls_raises() -> None:
    with pytest.raises(ValueError, match="assistant message must have content or tool_calls"):
        LLMMessage(role="assistant")


def test_tool_message_without_tool_call_id_raises() -> None:
    with pytest.raises(ValueError, match="tool message must have tool_call_id and content"):
        LLMMessage(role="tool", content="result")


def test_tool_message_without_content_raises() -> None:
    with pytest.raises(ValueError, match="tool message must have tool_call_id and content"):
        LLMMessage(role="tool", tool_call_id="call_1")


def test_tool_message_with_both_is_valid() -> None:
    m = LLMMessage(role="tool", tool_call_id="call_1", content="result")
    assert m.content == "result"


def test_system_message_without_content_raises() -> None:
    with pytest.raises(ValueError, match="system message must have content"):
        LLMMessage(role="system")


def test_user_message_without_content_raises() -> None:
    with pytest.raises(ValueError, match="user message must have content"):
        LLMMessage(role="user")


def test_llm_turn_constructs_with_stop() -> None:
    m = LLMMessage(role="assistant", content="done")
    turn = LLMTurn(assistant_message=m, finish_reason="stop")
    assert turn.finish_reason == "stop"
    assert turn.malformed_reason is None


def test_llm_turn_constructs_with_malformed_reason() -> None:
    m = LLMMessage(role="assistant", content="x")
    turn = LLMTurn(
        assistant_message=m,
        finish_reason="malformed",
        malformed_reason="unknown_finish_reason: 'foo'",
    )
    assert turn.malformed_reason == "unknown_finish_reason: 'foo'"

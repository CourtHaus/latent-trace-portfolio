"""Unit tests for the OpenAIClient adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from casesignal.worker.llm.openai_client import OpenAIClient
from casesignal.worker.llm.protocol import LLMMessage, ToolCall, ToolSchema


def _fake_response(
    *,
    content: str = "",
    tool_calls_json: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> MagicMock:
    """Build a MagicMock that mimics openai.types.chat.ChatCompletion."""
    response = MagicMock()
    message = MagicMock()
    message.content = content
    if tool_calls_json is not None:
        tcs = []
        for tc in tool_calls_json:
            mock_tc = MagicMock()
            mock_tc.id = tc["id"]
            mock_tc.function.name = tc["name"]
            mock_tc.function.arguments = tc["arguments"]  # raw JSON string
            tcs.append(mock_tc)
        message.tool_calls = tcs
    else:
        message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    response.choices = [choice]
    return response


def _patched_client() -> Any:
    """Context-manager helper that returns (OpenAIClient, mocked_create)."""
    return patch("casesignal.worker.llm.openai_client.OpenAI")


def test_adapter_sends_tools_in_openai_shape() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(content="hi")
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        tools = [
            ToolSchema(name="t", description="d", parameters={"type": "object", "properties": {}})
        ]
        client.chat(messages=[LLMMessage(role="user", content="hi")], tools=tools)

    call_kwargs = FakeOpenAI.return_value.chat.completions.create.call_args.kwargs
    assert call_kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "t",
                "description": "d",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_adapter_translates_messages_for_all_roles() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(content="ok")
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        tc = ToolCall(id="call_1", name="t", arguments={"a": 1})
        messages = [
            LLMMessage(role="system", content="sys"),
            LLMMessage(role="user", content="u"),
            LLMMessage(role="assistant", tool_calls=[tc]),
            LLMMessage(role="tool", tool_call_id="call_1", content="result"),
        ]
        client.chat(messages=messages, tools=[])

    sent = FakeOpenAI.return_value.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0] == {"role": "system", "content": "sys"}
    assert sent[1] == {"role": "user", "content": "u"}
    assert sent[2]["role"] == "assistant"
    assert sent[2]["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "t", "arguments": json.dumps({"a": 1})},
        }
    ]
    assert sent[3] == {"role": "tool", "tool_call_id": "call_1", "content": "result"}


def test_adapter_returns_stop_finish_reason() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(
            content="done", finish_reason="stop"
        )
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        turn = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[])

    assert turn.finish_reason == "stop"
    assert turn.assistant_message.content == "done"
    assert turn.assistant_message.tool_calls == []


def test_adapter_parses_tool_call_arguments_as_dict() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(
            tool_calls_json=[
                {
                    "id": "call_1",
                    "name": "homicide_jurisdiction_comparison",
                    "arguments": json.dumps({"jurisdiction_id": [109, 110], "source_year": 2022}),
                }
            ],
            finish_reason="tool_calls",
        )
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        turn = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[])

    assert turn.finish_reason == "tool_calls"
    assert len(turn.assistant_message.tool_calls) == 1
    tc = turn.assistant_message.tool_calls[0]
    assert tc.name == "homicide_jurisdiction_comparison"
    assert tc.arguments == {"jurisdiction_id": [109, 110], "source_year": 2022}


def test_adapter_translates_length_finish_reason() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(
            content="partial", finish_reason="length"
        )
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        turn = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[])

    assert turn.finish_reason == "length"


def test_adapter_translates_content_filter_finish_reason() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(
            content="", finish_reason="content_filter"
        )
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        turn = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[])

    assert turn.finish_reason == "content_filter"


def test_adapter_returns_malformed_for_unknown_finish_reason() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(
            content="x", finish_reason="weird_new_reason"
        )
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        turn = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[])

    assert turn.finish_reason == "malformed"
    assert turn.malformed_reason is not None
    assert "weird_new_reason" in turn.malformed_reason


def test_adapter_returns_malformed_for_bad_json_arguments() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(
            tool_calls_json=[{"id": "call_1", "name": "t", "arguments": "{not valid json"}],
            finish_reason="tool_calls",
        )
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        turn = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[])

    assert turn.finish_reason == "malformed"
    assert turn.malformed_reason is not None
    assert "call_1" in turn.malformed_reason


def test_adapter_propagates_transport_exceptions() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.side_effect = RuntimeError(
            "connection refused"
        )
        client = OpenAIClient(base_url="http://x", api_key="k", model="qwen2.5:7b")
        with pytest.raises(RuntimeError, match="connection refused"):
            client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[])


def test_adapter_sends_configured_model_and_max_tokens() -> None:
    with _patched_client() as FakeOpenAI:
        FakeOpenAI.return_value.chat.completions.create.return_value = _fake_response(content="ok")
        client = OpenAIClient(base_url="http://x", api_key="k", model="my-model")
        client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[], max_tokens=1024)

    call_kwargs = FakeOpenAI.return_value.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "my-model"
    assert call_kwargs["max_tokens"] == 1024


def test_adapter_passes_timeout_and_retries_to_underlying_client() -> None:
    with _patched_client() as FakeOpenAI:
        OpenAIClient(
            base_url="http://x",
            api_key="k",
            model="m",
            timeout=90.0,
            max_retries=5,
        )
    init_kwargs = FakeOpenAI.call_args.kwargs
    assert init_kwargs["timeout"] == 90.0
    assert init_kwargs["max_retries"] == 5


def test_adapter_defaults_timeout_and_retries() -> None:
    with _patched_client() as FakeOpenAI:
        OpenAIClient(base_url="http://x", api_key="k", model="m")
    init_kwargs = FakeOpenAI.call_args.kwargs
    assert init_kwargs["timeout"] == 240.0
    assert init_kwargs["max_retries"] == 3

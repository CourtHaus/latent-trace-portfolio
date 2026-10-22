"""OpenAI SDK adapter implementing LLMClient.

This is the one file that imports `openai`. The worker depends on the
protocol, not on this module directly.
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from casesignal.worker.llm.protocol import LLMMessage, LLMTurn, ToolCall, ToolSchema

_KNOWN_FINISH_REASONS = {"stop", "tool_calls", "length", "content_filter"}


class OpenAIClient:
    """LLMClient implementation backed by the OpenAI Python SDK.

    Works against any OpenAI-compatible endpoint: Ollama, Groq, OpenAI,
    Together, vLLM, LM Studio, etc.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float | None = None,
        timeout: float = 240.0,
        max_retries: int = 3,
    ) -> None:
        # Per-request HTTP timeout + SDK-level retry. Local Ollama runs have been
        # observed to silently stop responding mid-stream after long uptime —
        # without a timeout the worker blocks on poll() forever (see
        # reference-windows-ollama-from-wsl). The SDK retries timeouts and 5xx
        # responses with exponential backoff.
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._model = model
        self._temperature = temperature

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSchema],
        max_tokens: int = 2048,
    ) -> LLMTurn:
        openai_messages = [self._to_openai_message(m) for m in messages]
        openai_tools = [self._to_openai_tool(t) for t in tools] if tools else []

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature

        response = self._client.chat.completions.create(**kwargs)
        return self._from_openai_response(response)

    @staticmethod
    def _to_openai_tool(tool: ToolSchema) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    @staticmethod
    def _to_openai_message(message: LLMMessage) -> dict[str, Any]:
        if message.role == "tool":
            assert message.tool_call_id is not None  # invariant from __post_init__
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content,
            }
        if message.role == "assistant":
            out: dict[str, Any] = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                out["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in message.tool_calls
                ]
            return out
        # system, user
        return {"role": message.role, "content": message.content}

    @staticmethod
    def _from_openai_response(response: Any) -> LLMTurn:
        choice = response.choices[0]
        finish_reason = choice.finish_reason
        raw_message = choice.message

        content = raw_message.content or ""
        raw_tool_calls = getattr(raw_message, "tool_calls", None) or []

        parsed_tool_calls: list[ToolCall] = []
        for raw_tc in raw_tool_calls:
            try:
                args = json.loads(raw_tc.function.arguments or "{}")
            except json.JSONDecodeError:
                return _malformed_turn(
                    content=content or "(malformed tool call)",
                    reason=f"tool_call_arguments_not_json: id={raw_tc.id}",
                )
            if not isinstance(args, dict):
                return _malformed_turn(
                    content=content or "(malformed tool call)",
                    reason=f"tool_call_arguments_not_object: id={raw_tc.id}",
                )
            parsed_tool_calls.append(
                ToolCall(
                    id=raw_tc.id,
                    name=raw_tc.function.name,
                    arguments=args,
                )
            )

        # LLMMessage invariants: assistant must have content or tool_calls.
        # Ensure content is non-empty for valid finish reasons.
        if not content and not parsed_tool_calls:
            if finish_reason == "content_filter":
                content = "(filtered)"
            elif finish_reason in _KNOWN_FINISH_REASONS:
                return _malformed_turn(
                    content="(empty response)",
                    reason="assistant_message_empty",
                )

        assistant = LLMMessage(
            role="assistant",
            content=content,
            tool_calls=parsed_tool_calls,
        )

        if finish_reason in _KNOWN_FINISH_REASONS:
            return LLMTurn(assistant_message=assistant, finish_reason=finish_reason)

        return _malformed_turn(
            content=content or "(empty)",
            reason=f"unknown_finish_reason: {finish_reason!r}",
        )


def _malformed_turn(*, content: str, reason: str) -> LLMTurn:
    """Build an LLMTurn carrying a minimally-valid assistant message and a malformed marker."""
    return LLMTurn(
        assistant_message=LLMMessage(role="assistant", content=content),
        finish_reason="malformed",
        malformed_reason=reason,
    )

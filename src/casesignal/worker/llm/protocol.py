"""LLM client protocol and supporting dataclasses.

The worker depends on the LLMClient protocol, not on any vendor SDK.
Adapters (see openai_client.py) translate between these neutral types
and the wire format of a specific provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolSchema:
    """A tool definition offered to the model."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the tool's arguments


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]  # parsed JSON args (not a string)


@dataclass(frozen=True)
class LLMMessage:
    """One message in the conversation history.

    Invariants enforced in __post_init__:
      - assistant: must have content or tool_calls (not both empty)
      - tool: must have tool_call_id AND content
      - system / user: must have content
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.role == "assistant":
            if not self.content and not self.tool_calls:
                raise ValueError("assistant message must have content or tool_calls")
        elif self.role == "tool":
            if self.tool_call_id is None or not self.content:
                raise ValueError("tool message must have tool_call_id and content")
        elif self.role in ("system", "user"):
            if not self.content:
                raise ValueError(f"{self.role} message must have content")


@dataclass(frozen=True)
class LLMTurn:
    """Result of one chat() invocation."""

    assistant_message: LLMMessage
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter", "malformed"]
    malformed_reason: str | None = None  # only set when finish_reason == "malformed"


class LLMClient(Protocol):
    """A provider-agnostic chat-completions interface."""

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSchema],
        max_tokens: int = 2048,
    ) -> LLMTurn:
        """Send one turn of the conversation. Returns the assistant's reply."""
        ...

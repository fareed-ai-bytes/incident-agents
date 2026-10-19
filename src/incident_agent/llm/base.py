"""Chat-model interface shared by the raw loop and graph nodes.

Messages use the OpenAI chat format, which Ollama serves at /v1/chat/completions.
No framework imports here: raw_loop/ depends on this module.
"""

from __future__ import annotations

from typing import Any, NotRequired, Protocol, TypedDict


class ToolCallFunction(TypedDict):
    name: str
    arguments: str  # JSON-encoded, exactly as the model produced it (may be malformed)


class ToolCall(TypedDict):
    id: str
    type: str
    function: ToolCallFunction


class ChatMessage(TypedDict):
    role: str  # system | user | assistant | tool
    content: str
    tool_calls: NotRequired[list[ToolCall]]
    tool_call_id: NotRequired[str]
    name: NotRequired[str]


class ToolSchema(TypedDict):
    """OpenAI-style tool definition handed to the model."""

    type: str
    function: dict[str, Any]


class ModelError(RuntimeError):
    """The model endpoint failed (unreachable, timed out, bad response)."""


class ChatModel(Protocol):
    """Anything that turns a message list (plus optional tools) into one assistant message."""

    name: str

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
        *,
        purpose: str = "",
    ) -> ChatMessage: ...


def tool_schema(name: str, description: str, parameters: dict[str, Any]) -> ToolSchema:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }

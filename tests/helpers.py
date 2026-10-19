"""Test doubles: scripted chat models and tool-call builders."""

from __future__ import annotations

import json
from typing import Any


def tool_call(name: str, args: dict[str, Any] | str, thought: str = "") -> dict[str, Any]:
    arguments = args if isinstance(args, str) else json.dumps(args)
    return {
        "role": "assistant",
        "content": thought,
        "tool_calls": [
            {
                "id": f"c_{name}",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


def text_reply(content: str) -> dict[str, Any]:
    return {"role": "assistant", "content": content}


class ScriptedModel:
    """Returns the scripted replies in order; repeats the last one when exhausted."""

    name = "scripted"

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages, tools=None, *, purpose=""):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[idx]

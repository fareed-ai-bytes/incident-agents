"""Cheap token estimates (no tokenizer dependency): ~4 characters per token."""

from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def estimate_messages(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> int:
    """Approximate prompt size of a chat request, including tool schemas."""
    total = 0
    for m in messages:
        total += 4 + estimate_tokens(str(m.get("content") or ""))
        if m.get("tool_calls"):
            total += estimate_tokens(json.dumps(m["tool_calls"]))
    if tools:
        total += estimate_tokens(json.dumps(tools))
    return total

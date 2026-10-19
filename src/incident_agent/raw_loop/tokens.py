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


class TokenBudgetExceededError(RuntimeError):
    """A prompt cannot be made to fit its budget; it must not be sent."""


TRIM_MARKER = " ...[trimmed to fit token budget]"


def fit_to_budget(
    messages: list[dict[str, Any]], budget: int, tools: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Return a copy of `messages` that fits `budget`, trimming tool observations oldest first.

    System and user messages are never trimmed. Raises TokenBudgetExceededError when even
    fully trimmed observations leave the prompt over budget.
    """
    out = [dict(m) for m in messages]
    if estimate_messages(out, tools) <= budget:
        return out
    for m in out:
        if m.get("role") != "tool":
            continue
        over = estimate_messages(out, tools) - budget
        if over <= 0:
            break
        content = str(m.get("content") or "")
        keep = max(0, len(content) - over * CHARS_PER_TOKEN - len(TRIM_MARKER))
        m["content"] = content[:keep] + TRIM_MARKER
    size = estimate_messages(out, tools)
    if size > budget:
        raise TokenBudgetExceededError(f"prompt needs ~{size} tokens, budget is {budget}")
    return out

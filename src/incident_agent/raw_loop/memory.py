"""Conversation memory for the raw loop.

`Transcript` keeps every observation verbatim; `SlidingWindow` keeps the last N verbatim and
summarises older ones into `summary_note` (S34).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from incident_agent.llm.base import ChatMessage


@dataclass
class Exchange:
    call_id: str
    tool: str
    args: dict[str, Any]
    thought: str
    observation: str

    def messages(self) -> list[ChatMessage]:
        return [
            {
                "role": "assistant",
                "content": self.thought,
                "tool_calls": [
                    {
                        "id": self.call_id,
                        "type": "function",
                        "function": {"name": self.tool, "arguments": json.dumps(self.args)},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": self.call_id,
                "name": self.tool,
                "content": self.observation,
            },
        ]


@dataclass
class Transcript:
    exchanges: list[Exchange] = field(default_factory=list)
    summary_note: str = ""

    def add(
        self, call_id: str, tool: str, args: dict[str, Any], thought: str, observation: str
    ) -> None:
        self.exchanges.append(
            Exchange(f"{call_id}_{len(self.exchanges)}", tool, args, thought, observation)
        )

    def build(self, system: str, task: str) -> list[ChatMessage]:
        msgs: list[ChatMessage] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        for ex in self.exchanges:
            msgs.extend(ex.messages())
        return msgs


SUMMARY_PREFIX = "Summary of earlier observations"
MAX_SUMMARY_LINES = 30

_HIT = re.compile(r'\{"line": (\d+), "text": "((?:[^"\\]|\\.)*)"\}')
_SIGNAL = re.compile(r"ERROR|FATAL|WARN|failed|missing|expired|suspended|reset", re.I)


def summarise_exchange(ex: Exchange) -> list[str]:
    """Condense one old observation, keeping every signal-bearing log line verbatim."""
    head = f"- {ex.tool}({json.dumps(ex.args, sort_keys=True)})"
    hits = [(n, t) for n, t in _HIT.findall(ex.observation) if _SIGNAL.search(t)]
    if hits:
        return [head + ":"] + [f'  {{"line": {n}, "text": "{t}"}}' for n, t in hits]
    snippet = ex.observation[:160].replace("\n", " ")
    return [f"{head}: {snippet}"]


@dataclass
class SlidingWindow(Transcript):
    """Keeps the last `window` exchanges verbatim; older ones are summarised, not dropped."""

    window: int = 3
    _summary_lines: list[str] = field(default_factory=list)

    def add(
        self, call_id: str, tool: str, args: dict[str, Any], thought: str, observation: str
    ) -> None:
        super().add(call_id, tool, args, thought, observation)
        while len(self.exchanges) > self.window:
            oldest = self.exchanges.pop(0)
            self._summary_lines.extend(summarise_exchange(oldest))
        if len(self._summary_lines) > MAX_SUMMARY_LINES:
            # Keep the first lines (earliest evidence) and the most recent ones.
            half = MAX_SUMMARY_LINES // 2
            self._summary_lines = self._summary_lines[:half] + self._summary_lines[-half:]
        self.summary_note = "\n".join(self._summary_lines)

    def build(self, system: str, task: str) -> list[ChatMessage]:
        msgs = super().build(system, task)
        if self.summary_note:
            msgs.insert(
                2,
                {
                    "role": "user",
                    "content": f"{SUMMARY_PREFIX} (condensed; recent steps follow):\n"
                    f"{self.summary_note}",
                },
            )
        return msgs

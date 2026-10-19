"""Conversation memory for the raw loop.

`Transcript` keeps every observation verbatim. (S34 adds a sliding-window variant.)
"""

from __future__ import annotations

import json
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

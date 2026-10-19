"""Dependencies handed to graph nodes (model, MCP tools, settings, clock).

Nodes are built as closures over a Runtime, so they stay pure functions of state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from incident_agent.config import Settings
from incident_agent.llm.base import ChatModel
from incident_agent.mcp_client import ToolClient
from incident_agent.raw_loop.retry import RetryPolicy, call_with_retry


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Runtime:
    settings: Settings
    model: ChatModel
    tools: ToolClient
    clock: Callable[[], datetime] = field(default=utcnow)
    # Optional override of the verify node's health probe (tests force failures with it).
    health_check: Callable[[str, str], dict[str, Any]] | None = None

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(self.settings.max_tool_attempts, self.settings.retry_base_delay)

    def call_tool(self, name: str, args: dict[str, Any], incident_id: str) -> tuple[Any, int]:
        """Call any tool with retry; injects incident_id when the tool takes one."""
        props = self.tools.spec(name).input_schema.get("properties", {})
        if "incident_id" in props and "incident_id" not in args:
            args = {**args, "incident_id": incident_id}
        outcome = call_with_retry(
            lambda: self.tools.call(name, args), self.retry_policy, label=name
        )
        return outcome.value, outcome.attempts

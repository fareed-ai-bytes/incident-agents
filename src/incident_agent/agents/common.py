"""Helpers shared by worker agents: wrapping scoped MCP tools for the raw loop."""

from __future__ import annotations

from collections import Counter
from typing import Any

from incident_agent.mcp_client import ScopedTools
from incident_agent.mcp_client.schema import model_parameters
from incident_agent.raw_loop import LoopTool
from incident_agent.raw_loop.retry import RetryOutcome, RetryPolicy, call_with_retry


class RetryingTools:
    """A worker's scoped tools, with tool-level retry (BR-04) and retry counting."""

    def __init__(self, tools: ScopedTools, policy: RetryPolicy, incident_id: str) -> None:
        self.tools = tools
        self.policy = policy
        self.incident_id = incident_id
        self.retries: Counter[str] = Counter()

    def call(self, name: str, args: dict[str, Any]) -> Any:
        props = self.tools.specs[name].input_schema.get("properties", {})
        if "incident_id" in props:
            args = {**args, "incident_id": self.incident_id}
        outcome: RetryOutcome[Any] = call_with_retry(
            lambda: self.tools.call(name, args), self.policy, label=name
        )
        if outcome.attempts > 1:
            self.retries[name] += outcome.attempts - 1
        return outcome.value

    def loop_tools(self) -> list[LoopTool]:
        return [
            LoopTool(
                name=spec.name,
                description=spec.description,
                parameters=model_parameters(spec),
                fn=lambda args, _n=spec.name: self.call(_n, args),
            )
            for spec in self.tools.specs.values()
        ]


def clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0

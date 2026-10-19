"""Shared helpers for MCP tool modules: error mapping and per-tool risk metadata."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from incident_agent.config import Settings
from incident_agent.errors import PermanentToolError, ToolCallError
from incident_agent.mocks.job_runner import FakeJobRunner
from incident_agent.mocks.warehouse import WarehouseError
from incident_agent.models import RiskTier

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class ServerContext:
    settings: Settings
    runner: FakeJobRunner


def guarded(fn: F) -> F:
    """Convert domain errors into MCP ToolErrors whose message carries the classification."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ToolCallError as exc:
            raise ToolError(exc.wire_message()) from exc
        except (LookupError, WarehouseError, ValueError) as exc:
            raise ToolError(PermanentToolError(str(exc)).wire_message()) from exc

    return wrapper  # type: ignore[return-value]


def register(
    server: MCPServer, fn: Callable[..., Any], tier: RiskTier, category: str, description: str
) -> None:
    """Register `fn` as a tool; every tool declares its risk tier in `meta` (BR-01)."""
    server.add_tool(
        guarded(fn),
        name=fn.__name__,
        description=description,
        meta={"risk_tier": tier.value, "category": category},
    )

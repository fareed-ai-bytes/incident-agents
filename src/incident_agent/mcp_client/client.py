"""MCP client: discovers tools at runtime and exposes a synchronous call API.

Graph nodes are synchronous, while the MCP SDK is async. `ToolClient` owns one background
event loop and one long-lived MCP session; calls from any thread are queued onto it.

This module never imports the server package: it connects to whatever target it is given
(an stdio command, or an in-process server object in tests).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
import threading
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from incident_agent.config import SERVER_MODULE, Settings
from incident_agent.errors import PermanentToolError, classify_message
from incident_agent.log import get_logger
from incident_agent.models import RiskTier

log = get_logger(__name__)

# Arguments the executor supplies itself; never shown to (or chosen by) a model.
INJECTED_ARGS = frozenset({"incident_id", "approver", "approval_id", "step_index"})

DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_tier: RiskTier
    category: str

    @property
    def is_write(self) -> bool:
        return self.risk_tier is not RiskTier.READ


def stdio_target(settings: Settings) -> StdioServerParameters:
    """Launch the local MCP server as a child process speaking stdio."""
    env = {**os.environ, **settings.as_env()}
    return StdioServerParameters(command=sys.executable, args=["-m", SERVER_MODULE], env=env)


class _SessionThread:
    """One asyncio loop in a daemon thread holding one MCP session open."""

    def __init__(self, target: Any, timeout: float) -> None:
        self._target = target
        self._timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="mcp")
        self._thread.start()
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        asyncio.run_coroutine_threadsafe(self._start(), self._loop).result(timeout)

    async def _start(self) -> None:
        self._queue = asyncio.Queue()
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._serve(ready))
        await ready

    async def _serve(self, ready: asyncio.Future) -> None:
        try:
            async with Client(self._target, read_timeout_seconds=self._timeout) as client:
                ready.set_result(None)
                while True:
                    item = await self._queue.get()
                    if item is None:
                        return
                    fn, fut = item
                    try:
                        fut.set_result(await fn(client))
                    except Exception as exc:
                        fut.set_exception(exc)
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                log.exception("MCP session ended unexpectedly")

    def run(self, fn: Callable[[Client], Awaitable[Any]]) -> Any:
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (fn, fut))
        return fut.result(self._timeout)

    def close(self) -> None:
        if not self._thread.is_alive():
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        if self._task is not None:
            try:
                asyncio.run_coroutine_threadsafe(_wait(self._task), self._loop).result(10)
            except Exception:
                log.warning("MCP session did not close cleanly", exc_info=True)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)


async def _wait(task: asyncio.Task) -> None:
    await asyncio.wait({task})


class ToolClient:
    """Synchronous MCP client with runtime tool discovery."""

    def __init__(self, target: Any, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._session = _SessionThread(target, timeout)
        self._specs: dict[str, ToolSpec] | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> ToolClient:
        return cls(stdio_target(settings))

    def __enter__(self) -> ToolClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def discover(self, refresh: bool = False) -> dict[str, ToolSpec]:
        """List the server's tools (cached). Tools without a risk tier are rejected."""
        if self._specs is None or refresh:
            result = self._session.run(lambda c: c.list_tools())
            specs = {}
            for t in result.tools:
                meta = t.meta or {}
                if "risk_tier" not in meta:
                    raise PermanentToolError(f"tool {t.name!r} declares no risk_tier", t.name)
                specs[t.name] = ToolSpec(
                    name=t.name,
                    description=t.description or "",
                    input_schema=dict(t.input_schema),
                    risk_tier=RiskTier(meta["risk_tier"]),
                    category=str(meta.get("category", "")),
                )
            self._specs = specs
        return self._specs

    def spec(self, name: str) -> ToolSpec:
        try:
            return self.discover()[name]
        except KeyError:
            raise PermanentToolError(f"unknown tool {name!r}", name) from None

    def call(self, name: str, args: dict[str, Any]) -> Any:
        """Call a tool. Raises TransientToolError / PermanentToolError on failure."""
        self.spec(name)
        result = self._session.run(lambda c: c.call_tool(name, args))
        text = "".join(getattr(part, "text", "") for part in result.content)
        if result.is_error:
            raise classify_message(text, name)
        if result.structured_content is not None:
            return result.structured_content
        try:
            return json.loads(text)
        except ValueError:
            return text

    def scoped(self, allow: Iterable[str]) -> ScopedTools:
        return ScopedTools(self, frozenset(allow))


class ScopedTools:
    """The subset of tools one worker may use (an explicit allow-list)."""

    def __init__(self, client: ToolClient, allow: frozenset[str]) -> None:
        available = client.discover()
        unknown = allow - set(available)
        if unknown:
            raise PermanentToolError(f"allow-list names unknown tools: {sorted(unknown)}")
        self._client = client
        self.allow = allow
        self.specs = {n: available[n] for n in sorted(allow)}

    def call(self, name: str, args: dict[str, Any]) -> Any:
        if name not in self.allow:
            raise PermanentToolError(f"tool {name!r} is not in this worker's allow-list", name)
        return self._client.call(name, args)

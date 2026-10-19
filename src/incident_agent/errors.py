"""Tool error classification shared by mocks, the MCP layer and the retry helper (BR-04)."""

from __future__ import annotations

TRANSIENT_PREFIX = "[transient]"
PERMANENT_PREFIX = "[permanent]"


class ToolCallError(Exception):
    """Base class: a tool call failed."""

    kind = "permanent"

    def __init__(self, message: str, tool: str = "") -> None:
        super().__init__(message)
        self.tool = tool

    def wire_message(self) -> str:
        """Message as sent over MCP, prefixed with its classification."""
        prefix = TRANSIENT_PREFIX if self.kind == "transient" else PERMANENT_PREFIX
        return f"{prefix} {self}"


class TransientToolError(ToolCallError):
    """Timeouts, connection resets, throttling: safe to retry with backoff."""

    kind = "transient"


class PermanentToolError(ToolCallError):
    """Missing tables, bad arguments, refused approvals: never retried."""

    kind = "permanent"


def classify_message(message: str, tool: str = "") -> ToolCallError:
    """Rebuild a typed error from an MCP error message. Unprefixed errors count as permanent."""
    if TRANSIENT_PREFIX in message:
        return TransientToolError(message.split(TRANSIENT_PREFIX, 1)[1].strip(), tool)
    if PERMANENT_PREFIX in message:
        return PermanentToolError(message.split(PERMANENT_PREFIX, 1)[1].strip(), tool)
    return PermanentToolError(message, tool)

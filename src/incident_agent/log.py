"""Project logger. Use `get_logger(__name__)`; never print() outside cli/ (rules.md)."""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Send project logs to stderr, so CLI output on stdout stays clean."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("incident_agent")
    root.addHandler(handler)
    root.setLevel((level or os.environ.get("LOG_LEVEL", "WARNING")).upper())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(
        name if name.startswith("incident_agent") else f"incident_agent.{name}"
    )


class _NodeAdapter(logging.LoggerAdapter):
    def process(self, msg: object, kwargs: dict) -> tuple[str, dict]:
        extra = self.extra or {}
        return f"[{extra.get('incident_id')} {extra.get('node')}] {msg}", kwargs


def node_logger(name: str, incident_id: str, node: str) -> logging.LoggerAdapter:
    """Logger that stamps every record with incident_id and node name (rules.md)."""
    return _NodeAdapter(get_logger(name), {"incident_id": incident_id, "node": node})

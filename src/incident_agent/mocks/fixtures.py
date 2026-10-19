"""Read access to the committed fixtures (logs, alerts, source schemas)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import TypedDict

from incident_agent.mocks.scenarios import scenario_for_pipeline


class LogLine(TypedDict):
    line: int
    text: str


class SourceSchema(TypedDict):
    table: str
    columns: list[dict[str, str]]


@lru_cache(maxsize=16)
def _log_lines(pipeline: str) -> tuple[str, ...]:
    path = scenario_for_pipeline(pipeline).log_path
    return tuple(path.read_text(encoding="utf-8").splitlines())


def log_length(pipeline: str) -> int:
    return len(_log_lines(pipeline))


def log_window(pipeline: str, offset: int, limit: int) -> list[LogLine]:
    """Lines [offset, offset+limit) using 1-based line numbers."""
    lines = _log_lines(pipeline)
    start = max(offset, 1)
    return [
        {"line": i, "text": lines[i - 1]} for i in range(start, min(start + limit, len(lines) + 1))
    ]


def search_log(pipeline: str, pattern: str, max_hits: int = 20) -> list[LogLine]:
    rx = re.compile(pattern, re.IGNORECASE)
    hits: list[LogLine] = []
    for i, text in enumerate(_log_lines(pipeline), start=1):
        if rx.search(text):
            hits.append({"line": i, "text": text})
            if len(hits) >= max_hits:
                break
    return hits


def load_alert(scenario_id: str) -> dict:
    from incident_agent.mocks.scenarios import get_scenario

    return json.loads((get_scenario(scenario_id).fixture_dir / "alert.json").read_text("utf-8"))


def source_schema(pipeline: str) -> SourceSchema:
    path = scenario_for_pipeline(pipeline).fixture_dir / "source_schema.json"
    return json.loads(path.read_text(encoding="utf-8"))

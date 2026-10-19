"""Deterministic offline stand-in for a local model (MODEL_PROVIDER=heuristic).

It speaks the same chat/tool-call protocol as Ollama, so every code path (parsing, re-prompts,
tool calls, plan validation) is exercised. It exists for CI and for demos on machines without
Ollama; it is NOT evidence that a real local model can do the job (verification.md rule 3).
"""

from __future__ import annotations

import json
import re
from typing import Any

from incident_agent.llm.base import ChatMessage, ToolSchema
from incident_agent.raw_loop.memory import SUMMARY_PREFIX

# The "knowledge" of this model: log signatures -> (category, root cause template).
SIGNATURES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r'column \\?"?(\w+)\\?"? not found in target table|invalid identifier', re.I),
        "SCHEMA_DRIFT",
        "Source schema added column {0} that does not exist in the warehouse target table",
    ),
    (
        re.compile(r"authentication failed|password expired|invalid credentials", re.I),
        "AUTH_FAILURE",
        "Connector service user credentials expired; authentication to the source failed",
    ),
    (
        re.compile(r"warehouse (\w+) is suspended|warehouse \w+ suspended", re.I),
        "WAREHOUSE_UNAVAILABLE",
        "Warehouse {0} is suspended with auto_resume disabled, so the load could not run",
    ),
    (
        re.compile(r"partition (dt=[\d-]+) missing|late upstream delivery|not arrived", re.I),
        "LATE_DATA",
        "Upstream partition {0} arrived late, so the daily load found no data",
    ),
    (
        re.compile(r"connection reset by peer|ConnectionResetError|timed out", re.I),
        "TRANSIENT_NETWORK",
        "Transient network failure (connection reset) talking to the source API",
    ),
]

_BENIGN = re.compile(r"non-fatal|ignored|recovered", re.I)
_HIT = re.compile(r'\{"line": (\d+), "text": "((?:[^"\\]|\\.)*)"\}')


def match_signature(text: str) -> tuple[str, str] | None:
    """(category, root_cause) for the first signature matching `text`, ignoring benign lines."""
    if _BENIGN.search(text):
        return None
    for rx, category, template in SIGNATURES:
        m = rx.search(text)
        if m:
            groups = [g for g in m.groups() if g] or ["(unknown)"]
            return category, template.format(*groups)
    return None


def _call(name: str, args: dict[str, Any], thought: str = "") -> ChatMessage:
    return {
        "role": "assistant",
        "content": thought,
        "tool_calls": [
            {
                "id": f"h_{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


_TRIAGE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"invalid identifier|column .* not found|schema", re.I), "SCHEMA_DRIFT"),
    (re.compile(r"authenticat|credential|password|login", re.I), "AUTH_FAILURE"),
    (re.compile(r"suspended|warehouse .* unavailable", re.I), "WAREHOUSE_UNAVAILABLE"),
    (re.compile(r"freshness|partition .* missing|late (data|arrival)", re.I), "LATE_DATA"),
    (re.compile(r"connection reset|timed out|timeout|network", re.I), "TRANSIENT_NETWORK"),
]


class HeuristicModel:
    name = "heuristic"

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
        *,
        purpose: str = "",
    ) -> ChatMessage:
        handler = getattr(self, f"_{purpose}", None)
        if handler is None:
            return {"role": "assistant", "content": "{}"}
        return handler(messages)

    # -- Triage ---------------------------------------------------------------------------

    def _triage(self, messages: list[ChatMessage]) -> ChatMessage:
        text = messages[-1]["content"]
        try:
            alert = json.loads(text.split("Alert:", 1)[1])
            text = f"{alert.get('summary', '')} {alert.get('message', '')}"
        except (IndexError, ValueError, AttributeError):
            pass
        label = next((t for rx, t in _TRIAGE_RULES if rx.search(text)), "UNKNOWN")
        return {"role": "assistant", "content": json.dumps({"alert_type": label})}

    # -- Log Analyst ------------------------------------------------------------------------

    def _log_analyst(self, messages: list[ChatMessage]) -> ChatMessage:
        task = next((m["content"] for m in messages if m["role"] == "user"), "")
        pipeline_m = re.search(r"pipeline: (\S+)", task)
        pipeline = pipeline_m.group(1) if pipeline_m else ""
        observations = [(m.get("name", ""), m["content"]) for m in messages if m["role"] == "tool"]
        # A sliding-window summary of older observations counts as already seen.
        summary = next(
            (m["content"] for m in messages if m["content"].startswith(SUMMARY_PREFIX)), ""
        )
        searches = [o for n, o in observations if n == "search_logs"]
        windows = [o for n, o in observations if n == "fetch_log_window"]
        if summary:
            searches.append(summary)
            if "fetch_log_window" in summary:
                windows.append(summary)
        if not searches:
            return _call(
                "search_logs",
                {"pipeline": pipeline, "pattern": "ERROR|FATAL"},
                "Start by searching the log for error lines.",
            )

        hits = [(int(n), json.loads(f'"{t}"')) for o in searches for n, t in _HIT.findall(o)]
        best = next(((ln, txt, sig) for ln, txt in hits if (sig := match_signature(txt))), None)
        if best is None:
            return _call(
                "final_answer",
                {
                    "root_cause": "No known failure signature found in the error lines",
                    "category": "UNKNOWN",
                    "evidence": [f"L{ln}: {txt}" for ln, txt in hits[:3]],
                    "confidence": 0.3,
                },
            )
        line, text, (category, root_cause) = best
        if not windows:
            return _call(
                "fetch_log_window",
                {"pipeline": pipeline, "offset": max(1, line - 3), "limit": 8},
                f"Line {line} looks like the root cause; read its context.",
            )
        context = [
            f"L{n}: {json.loads(f'{chr(34)}{t}{chr(34)}')}"
            for o in windows
            for n, t in _HIT.findall(o)
            if int(n) != line and re.search(r"WARN|schema|sensor|retry", t)
        ]
        return _call(
            "final_answer",
            {
                "root_cause": root_cause,
                "category": category,
                "evidence": [f"L{line}: {text}", *context[:2]],
                "confidence": 0.85,
            },
            "The error line and its context agree.",
        )

    # -- Planner ----------------------------------------------------------------------------

    def _planner(self, messages: list[ChatMessage]) -> ChatMessage:
        user = next(m["content"] for m in messages if m["role"] == "user")
        diag_text, ctx_text = user.split("Context (from READ tools):", 1)
        diagnosis = json.loads(diag_text.split("Diagnosis:", 1)[1])
        context = json.loads(ctx_text)
        steps = playbook(diagnosis["category"], context)
        return {"role": "assistant", "content": json.dumps({"steps": steps})}


def playbook(category: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Standard remediation for each failure type (what an experienced on-call would do)."""
    info = context.get("pipeline_info", {})
    pipeline = info.get("pipeline", "")
    health = {
        "tool": "check_pipeline_health",
        "args": {"pipeline": pipeline},
        "rationale": "confirm the fix",
    }
    rerun = {
        "tool": "rerun_job",
        "args": {"pipeline": pipeline},
        "rationale": "reload with the fix in place",
    }
    if category == "SCHEMA_DRIFT":
        added = context.get("schema_diff", {}).get("added", [])
        return [
            {
                "tool": "alter_table",
                "args": {"table": info.get("table", ""), "add_columns": added},
                "rationale": "add the columns the source started sending",
            },
            rerun,
            health,
        ]
    if category == "AUTH_FAILURE":
        return [
            {
                "tool": "rotate_credentials",
                "args": {"connector_user": info.get("connector_user", "")},
                "rationale": "the service user's password expired",
            },
            rerun,
            health,
        ]
    if category == "WAREHOUSE_UNAVAILABLE":
        return [
            {
                "tool": "get_warehouse_status",
                "args": {"warehouse_name": info.get("warehouse", "")},
                "rationale": "confirm the warehouse is still suspended",
            },
            {
                "tool": "resume_warehouse",
                "args": {"warehouse_name": info.get("warehouse", "")},
                "rationale": "resume the suspended warehouse",
            },
            rerun,
            health,
        ]
    if category == "LATE_DATA":
        part = {"table": info.get("table", ""), "partition": info.get("partition", "")}
        return [
            {
                "tool": "check_partition_arrival",
                "args": part,
                "rationale": "has the partition landed now?",
            },
            {"tool": "backfill_partition", "args": part, "rationale": "reload the late partition"},
            health,
        ]
    if category == "TRANSIENT_NETWORK":
        return [
            {
                "tool": "get_job_status",
                "args": {"pipeline": pipeline},
                "rationale": "the scheduler retries transient failures; confirm the retry succeeded",
            },
            health,
        ]
    return []

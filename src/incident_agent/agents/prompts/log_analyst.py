"""Prompts for the Log Analyst (raw ReAct loop)."""

from __future__ import annotations

from incident_agent.models import AlertType

SYSTEM = """You are the Log Analyst on a data-pipeline on-call team.
Find the ROOT CAUSE of a failed load by reading the pipeline log with the tools provided.

Work in small steps:
1. search_logs for error signals (e.g. pattern "ERROR|FATAL").
2. fetch_log_window around the most specific error to read its context.
   Logs are paged: never request more than {page_size} lines at once.
3. Ignore lines marked non-fatal, ignored or recovered; the generic "finished with status
   FAILED" line is a symptom, not a cause.
4. When confident, call final_answer. Cite evidence as "L<line>: <text>".

Categories: {categories}.
Always reply with exactly one tool call."""

TASK = """Incident {incident_id}
pipeline: {pipeline}
alert type (from triage): {alert_type}
alert: {summary} -- {message}

Find the root cause in the log of pipeline {pipeline}."""

FINAL_PARAMETERS = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string", "description": "one sentence"},
        "category": {"type": "string", "enum": [t.value for t in AlertType]},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["root_cause", "category", "evidence", "confidence"],
}


def system_prompt(page_size: int) -> str:
    return SYSTEM.format(page_size=page_size, categories=", ".join(t.value for t in AlertType))

"""Schema Inspector (S22): detects source vs. warehouse schema drift with metadata tools.

A deterministic tool workflow (no model call): drift detection is a set comparison, and
keeping it model-free gives the aggregator one high-precision signal to weigh against.
"""

from __future__ import annotations

from incident_agent.agents.common import RetryingTools
from incident_agent.errors import ToolCallError
from incident_agent.mcp_client import ScopedTools
from incident_agent.models import NO_ISSUE, Alert, AlertType, Finding
from incident_agent.raw_loop.retry import RetryPolicy

WORKER = "schema_inspector"
ALLOWED_TOOLS = frozenset(
    {"get_pipeline_info", "compare_source_schema", "get_source_schema", "get_warehouse_schema"}
)


def run_schema_inspector(
    tools: ScopedTools, alert: Alert, incident_id: str, policy: RetryPolicy, round_no: int = 1
) -> tuple[Finding, dict[str, int]]:
    t = RetryingTools(tools, policy, incident_id)
    pipeline = alert["pipeline"]
    try:
        diff = t.call("compare_source_schema", {"pipeline": pipeline})
    except ToolCallError as exc:
        return _failed(f"schema comparison failed: {exc}", round_no), dict(t.retries)

    table = diff["table"]
    evidence = [f"compare_source_schema({pipeline}): table {table}"]
    evidence += [f"source added column {c['name']} {c['type']}" for c in diff["added"]]
    evidence += [f"source removed column {c['name']}" for c in diff["removed"]]
    evidence += [
        f"column {c['name']} type {c['target_type']} -> {c['source_type']}"
        for c in diff["type_changed"]
    ]
    if diff["drift"]:
        cols = ", ".join(f"{c['name']} {c['type']}" for c in diff["added"]) or "changed columns"
        finding: Finding = {
            "worker": WORKER,
            "category": AlertType.SCHEMA_DRIFT.value,
            "root_cause": f"Source schema drift on {table}: {cols} not present in the warehouse table",
            "evidence": evidence,
            "confidence": 0.9,
            "status": "complete",
            "round": round_no,
        }
    else:
        finding = {
            "worker": WORKER,
            "category": NO_ISSUE,
            "root_cause": f"Source and warehouse schemas for {table} match",
            "evidence": evidence,
            "confidence": 0.8,
            "status": "complete",
            "round": round_no,
        }
    return finding, dict(t.retries)


def _failed(reason: str, round_no: int) -> Finding:
    return {
        "worker": WORKER,
        "category": AlertType.UNKNOWN.value,
        "root_cause": reason,
        "evidence": [],
        "confidence": 0.0,
        "status": "failed",
        "round": round_no,
    }

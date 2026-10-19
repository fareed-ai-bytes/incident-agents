"""Warehouse Agent (S23): checks warehouse state, partition arrival and the load audit.

Deterministic tool workflow over READ tools; each signal is reported only when a tool result
shows it, so a running warehouse never yields a "suspended" finding.
"""

from __future__ import annotations

from incident_agent.agents.common import RetryingTools
from incident_agent.errors import ToolCallError
from incident_agent.mcp_client import ScopedTools
from incident_agent.models import NO_ISSUE, Alert, AlertType, Finding
from incident_agent.raw_loop.retry import RetryPolicy

WORKER = "warehouse_agent"
ALLOWED_TOOLS = frozenset(
    {
        "get_pipeline_info",
        "get_warehouse_status",
        "get_load_audit",
        "check_partition_arrival",
        "get_job_status",
    }
)


def run_warehouse_agent(
    tools: ScopedTools, alert: Alert, incident_id: str, policy: RetryPolicy, round_no: int = 1
) -> tuple[Finding, dict[str, int]]:
    t = RetryingTools(tools, policy, incident_id)
    pipeline = alert["pipeline"]
    try:
        info = t.call("get_pipeline_info", {"pipeline": pipeline})
        wh = t.call("get_warehouse_status", {"warehouse_name": info["warehouse"]})
        audit = t.call("get_load_audit", {"pipeline": pipeline, "limit": 3})
        partition = (
            t.call(
                "check_partition_arrival", {"table": info["table"], "partition": info["partition"]}
            )
            if info.get("partition")
            else None
        )
    except ToolCallError as exc:
        return _finding(
            AlertType.UNKNOWN.value, f"warehouse checks failed: {exc}", [], 0.0, round_no, "failed"
        ), dict(t.retries)

    evidence = [
        f"get_warehouse_status: {wh['warehouse']} state={wh['state']} auto_resume={wh['auto_resume']}"
    ]
    runs = audit.get("runs", [])
    if runs:
        last = runs[0]
        evidence.append(f"load_audit: {last['run_id']} {last['status']} {last['error']}".strip())
    if partition is not None:
        evidence.append(
            f"check_partition_arrival: {partition['table']} {partition['partition']} arrived={partition['arrived']}"
        )

    if wh["state"] == "SUSPENDED" and not wh["auto_resume"]:
        finding = _finding(
            AlertType.WAREHOUSE_UNAVAILABLE.value,
            f"Warehouse {wh['warehouse']} is suspended and auto_resume is disabled",
            evidence,
            0.9,
            round_no,
        )
    elif partition is not None and partition["arrived"] is False:
        finding = _finding(
            AlertType.LATE_DATA.value,
            f"Partition {partition['partition']} of {partition['table']} has not arrived",
            evidence,
            0.85,
            round_no,
        )
    else:
        finding = _finding(
            NO_ISSUE,
            f"Warehouse {wh['warehouse']} is running and inputs are present",
            evidence,
            0.7,
            round_no,
        )
    return finding, dict(t.retries)


def _finding(
    category: str,
    root_cause: str,
    evidence: list[str],
    confidence: float,
    round_no: int,
    status: str = "complete",
) -> Finding:
    return {
        "worker": WORKER,
        "category": category,
        "root_cause": root_cause,
        "evidence": evidence,
        "confidence": confidence,
        "status": status,
        "round": round_no,
    }

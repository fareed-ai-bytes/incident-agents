"""Executor (S29): runs plan steps in order and stops at the first failure.

Gated steps (REVERSIBLE / DESTRUCTIVE) run only when every gated step has an `approved`
decision recorded in state. A rejection anywhere means nothing runs (BR-09); an expired request
means nothing runs (BR-08). Write tools are reachable only from here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from langchain_core.messages import AIMessage

from incident_agent.errors import ToolCallError
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import IncidentState, PendingApproval
from incident_agent.log import node_logger
from incident_agent.models import ApprovalDecision, IncidentStatus, StepResult
from incident_agent.policy.risk import gated_steps, requires_approval


def latest_decisions(state: IncidentState) -> dict[str, ApprovalDecision]:
    out: dict[str, ApprovalDecision] = {}
    for d in state.get("approvals", []):
        out[d["approval_id"]] = d
    return out


def is_expired(pending: PendingApproval, now: datetime, ttl_hours: float) -> bool:
    requested = datetime.fromisoformat(pending["requested_at"])
    return now - requested > timedelta(hours=ttl_hours)


def make_execute_node(rt: Runtime, name: str) -> Callable[[IncidentState], dict[str, Any]]:
    def execute(state: IncidentState) -> dict[str, Any]:
        incident_id = state["incident_id"]
        log = node_logger(__name__, incident_id, name)
        plan = state["plan"]
        pending = state.get("pending_approval")
        decisions = latest_decisions(state)

        def stop(status: str, why: str) -> dict[str, Any]:
            log.warning("not executing: %s", why)
            return {
                "execution_status": status,
                "step_results": [],
                "messages": [AIMessage(content=f"{name}: {why}", name=name)],
                "node_log": [name],
            }

        by_step: dict[int, ApprovalDecision] = {}
        if gated_steps(plan):
            if not pending:
                return stop("REJECTED", "gated steps have no approval request")
            if is_expired(pending, rt.clock(), rt.settings.approval_ttl_hours):
                return stop("EXPIRED", "approval request expired")
            for item in pending["items"]:
                decision = decisions.get(item["approval_id"])
                if decision is None or decision["decision"] != "approved":
                    verdict = decision["decision"] if decision else "missing"
                    return stop("REJECTED", f"step {item['step_index']} {item['tool']}: {verdict}")
                by_step[item["step_index"]] = {
                    **decision,
                    "args": decision.get("args") or item["args"],
                }

        results: list[StepResult] = []
        status = "SUCCEEDED"
        for step in plan:
            args = dict(step["args"])
            if requires_approval(step["risk_tier"]):
                d = by_step.get(step["index"])
                if d is None:  # plan changed after approval: refuse rather than guess
                    status = "REJECTED"
                    break
                args = {
                    **d["args"],
                    "approver": d["approver"],
                    "approval_id": d["approval_id"],
                    "step_index": step["index"],
                }
            try:
                output, attempts = rt.call_tool(step["tool"], args, incident_id)
            except ToolCallError as exc:
                log.warning("step %d %s failed: %s", step["index"], step["tool"], exc)
                results.append(
                    {
                        "index": step["index"],
                        "tool": step["tool"],
                        "status": "FAILED",
                        "output": f"{exc.kind}: {exc}",
                        "attempts": rt.settings.max_tool_attempts if exc.kind == "transient" else 1,
                    }
                )
                status = "FAILED"
                break
            results.append(
                {
                    "index": step["index"],
                    "tool": step["tool"],
                    "status": "SUCCEEDED",
                    "output": output,
                    "attempts": attempts,
                }
            )
        retries = {f"{name}.{r['tool']}": r["attempts"] - 1 for r in results if r["attempts"] > 1}
        summary = ", ".join(f"{r['tool']}={r['status']}" for r in results) or "nothing run"
        return {
            "execution_status": status,
            "step_results": results,
            "pending_approval": None,
            "retry_counts": retries,
            "status": IncidentStatus.EXECUTED.value
            if status == "SUCCEEDED"
            else IncidentStatus.FAILED.value,
            "messages": [AIMessage(content=f"{name}: {summary}", name=name)],
            "node_log": [name],
        }

    return execute

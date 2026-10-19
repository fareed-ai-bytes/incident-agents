"""Routing: the supervisor's routing table and every conditional-edge function.

Routing functions are pure: they read state and return the next node name(s).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import Send

from incident_agent.graph.state import IncidentState, WorkerInput
from incident_agent.models import AlertType, IncidentStatus

LOG_ANALYST = "log_analyst"
SCHEMA_INSPECTOR = "schema_inspector"
WAREHOUSE_AGENT = "warehouse_agent"
WORKERS = (LOG_ANALYST, SCHEMA_INSPECTOR, WAREHOUSE_AGENT)

FALLBACK = "fallback"
SUPERVISOR = "supervisor"

# architecture.md, FR-02. UNKNOWN never reaches the supervisor (triage routes it to fallback).
ROUTING_TABLE: dict[AlertType, tuple[str, ...]] = {
    AlertType.SCHEMA_DRIFT: (LOG_ANALYST, SCHEMA_INSPECTOR),
    AlertType.AUTH_FAILURE: (LOG_ANALYST,),
    AlertType.WAREHOUSE_UNAVAILABLE: (WAREHOUSE_AGENT, LOG_ANALYST),
    AlertType.LATE_DATA: (WAREHOUSE_AGENT, LOG_ANALYST),
    AlertType.TRANSIENT_NETWORK: (LOG_ANALYST,),
}


def workers_for(alert_type: str) -> tuple[str, ...]:
    try:
        return ROUTING_TABLE[AlertType(alert_type)]
    except (ValueError, KeyError):
        return ()


def route_after_triage(state: IncidentState) -> str:
    return SUPERVISOR if workers_for(state.get("alert_type", "")) else FALLBACK


def supervisor(state: IncidentState) -> dict[str, Any]:
    """Pick the workers for this alert type and open a new diagnosis round."""
    workers = list(workers_for(state["alert_type"]))
    rnd = state.get("diagnosis_round", 0) + 1
    return {
        "active_workers": workers,
        "diagnosis_round": rnd,
        "status": IncidentStatus.DIAGNOSING.value,
        "messages": [
            AIMessage(content=f"supervisor: round {rnd} -> {', '.join(workers)}", name=SUPERVISOR)
        ],
        "node_log": [SUPERVISOR],
    }


def route_to_workers(state: IncidentState) -> list[Send]:
    """Fan out: one Send per active worker; they run in parallel in one superstep."""
    payload: WorkerInput = {
        "incident_id": state["incident_id"],
        "alert": state["alert"],
        "alert_type": state["alert_type"],
        "diagnosis_round": state["diagnosis_round"],
    }
    return [Send(worker, payload) for worker in state["active_workers"]]


PLANNER = "planner"


def make_route_after_aggregate(threshold: float):
    """Diagnosis confidence below the threshold (BR-03) or UNKNOWN goes to fallback (FR-05)."""

    def route_after_aggregate(state: IncidentState) -> str:
        diag = state.get("diagnosis")
        if not diag or diag["category"] == AlertType.UNKNOWN.value:
            return FALLBACK
        return PLANNER if diag["confidence"] >= threshold else FALLBACK

    return route_after_aggregate


REQUEST_APPROVAL = "request_approval"
EXECUTE = "execute"
EXECUTE_AUTO = "execute_auto"
VERIFY = "verify"


def route_after_plan(state: IncidentState) -> str:
    """No plan -> fallback; any gated step -> approval gate; READ-only -> run unattended."""
    plan = state.get("plan") or []
    if state.get("plan_error") or not plan:
        return FALLBACK
    if any(step["risk_tier"] != "READ" for step in plan):
        return REQUEST_APPROVAL
    return EXECUTE_AUTO


def route_after_execute(state: IncidentState) -> str:
    return VERIFY if state.get("execution_status") == "SUCCEEDED" else FALLBACK

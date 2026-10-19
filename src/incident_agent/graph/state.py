"""IncidentState: the LangGraph state schema and its reducers (S18).

Nodes return partial dict updates only. Reducers decide how updates merge:
- messages      add_messages (append / replace by id)
- findings      list append, so parallel workers never overwrite each other
- approvals     list append (decision history is never rewritten)
- node_log      list append (which nodes ran, used to prove resume skips completed work)
- retry_counts, reprompt_counts   summed per key
- token_usage   max per key
Everything else is last-write-wins.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from incident_agent.models import (
    Alert,
    ApprovalDecision,
    Diagnosis,
    Finding,
    PlanStep,
    StepResult,
)


def sum_counts(left: dict[str, int] | None, right: dict[str, int] | None) -> dict[str, int]:
    out = dict(left or {})
    for key, value in (right or {}).items():
        out[key] = out.get(key, 0) + value
    return out


def max_counts(left: dict[str, int] | None, right: dict[str, int] | None) -> dict[str, int]:
    out = dict(left or {})
    for key, value in (right or {}).items():
        out[key] = max(out.get(key, 0), value)
    return out


class ApprovalItem(TypedDict):
    approval_id: str
    step_index: int
    tool: str
    args: dict[str, Any]
    risk_tier: str
    rationale: str
    before: list[str]
    after: list[str]


class PendingApproval(TypedDict):
    incident_id: str
    requested_at: str
    items: list[ApprovalItem]


class Escalation(TypedDict):
    reason: str
    summary: str


class IncidentState(TypedDict, total=False):
    incident_id: str
    scenario: str
    alert: Alert
    alert_type: str
    status: str
    messages: Annotated[list[AnyMessage], add_messages]
    findings: Annotated[list[Finding], operator.add]
    diagnosis_round: int
    active_workers: list[str]
    diagnosis: Diagnosis | None
    plan: list[PlanStep]
    plan_error: str
    pending_approval: PendingApproval | None
    approvals: Annotated[list[ApprovalDecision], operator.add]
    step_results: list[StepResult]
    execution_status: str  # "" | SUCCEEDED | FAILED | REJECTED | EXPIRED
    retry_counts: Annotated[dict[str, int], sum_counts]
    reprompt_counts: Annotated[dict[str, int], sum_counts]
    token_usage: Annotated[dict[str, int], max_counts]
    verify_attempts: int
    healthy: bool
    summary_note: str
    escalation: Escalation | None
    node_log: Annotated[list[str], operator.add]


class WorkerInput(TypedDict):
    """Payload a supervisor `Send` hands to one worker (not the whole state)."""

    incident_id: str
    alert: Alert
    alert_type: str
    diagnosis_round: int


def initial_state(incident_id: str, scenario: str, alert: Alert) -> IncidentState:
    return {
        "incident_id": incident_id,
        "scenario": scenario,
        "alert": alert,
        "alert_type": "",
        "status": "NEW",
        "messages": [],
        "findings": [],
        "diagnosis_round": 0,
        "active_workers": [],
        "diagnosis": None,
        "plan": [],
        "plan_error": "",
        "pending_approval": None,
        "approvals": [],
        "step_results": [],
        "execution_status": "",
        "retry_counts": {},
        "reprompt_counts": {},
        "token_usage": {},
        "verify_attempts": 0,
        "healthy": False,
        "summary_note": "",
        "escalation": None,
        "node_log": [],
    }


def current_findings(state: IncidentState) -> list[Finding]:
    """Findings from the latest diagnosis round only (re-diagnosis appends a new round)."""
    rnd = state.get("diagnosis_round", 0)
    return [f for f in state.get("findings", []) if f["round"] == rnd]

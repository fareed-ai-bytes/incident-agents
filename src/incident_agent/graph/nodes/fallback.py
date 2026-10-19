"""Fallback escalation (S21): every dead end produces a human-readable hand-off, never silence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from incident_agent.config import Settings
from incident_agent.graph.state import Escalation, IncidentState, current_findings
from incident_agent.log import node_logger
from incident_agent.models import AlertType, IncidentStatus

NODE = "fallback"

REASONS = {
    "unknown_alert": (
        "Alert could not be classified into a known failure type.",
        "Read the alert and logs manually; add a scenario/signature if this recurs.",
    ),
    "low_confidence": (
        "Diagnosis confidence is below the escalation threshold.",
        "Review the conflicting findings below and confirm the root cause by hand.",
    ),
    "planner_failed": (
        "No valid remediation plan could be produced.",
        "Draft the fix manually using the diagnosis below.",
    ),
    "approval_rejected": (
        "An approver rejected the proposed action (BR-09).",
        "Agree an alternative fix with the approver; nothing was executed.",
    ),
    "approval_expired": (
        "The approval request expired before anyone decided (BR-08).",
        "Re-run the incident to get a fresh plan; nothing was executed.",
    ),
    "execution_failed": (
        "A remediation step failed; later steps were not run.",
        "Inspect the failed step below and the audit log before retrying.",
    ),
    "verify_failed": (
        "The pipeline is still unhealthy after remediation and one re-diagnosis (BR-06).",
        "Hand over to the platform owner with the actions taken so far.",
    ),
}


def escalation_reason(state: IncidentState, settings: Settings) -> str:
    """Why this incident ended up in fallback, checking the latest stage first."""
    status = state.get("execution_status", "")
    if status == "REJECTED":
        return "approval_rejected"
    if status == "EXPIRED":
        return "approval_expired"
    if status == "FAILED":
        return "execution_failed"
    if state.get("verify_attempts", 0) >= settings.max_verify_attempts and not state.get("healthy"):
        return "verify_failed"
    if state.get("plan_error"):
        return "planner_failed"
    if state.get("alert_type") in ("", AlertType.UNKNOWN.value):
        return "unknown_alert"
    return "low_confidence"


def build_summary(state: IncidentState, reason: str) -> str:
    alert = state.get("alert") or {}
    headline, next_step = REASONS[reason]
    lines = [
        f"ESCALATED: {headline}",
        f"Incident {state.get('incident_id')} | pipeline {alert.get('pipeline', '?') if isinstance(alert, dict) else '?'}"
        f" | alert type {state.get('alert_type') or 'UNKNOWN'}",
    ]
    if isinstance(alert, dict) and alert:
        lines.append(f"Alert: {alert.get('summary', '')} -- {alert.get('message', '')}")
    diag = state.get("diagnosis")
    if diag:
        lines.append(
            f"Diagnosis: {diag['root_cause']} ({diag['category']}, confidence {diag['confidence']:.2f})"
        )
        lines.extend(f"Conflict: {c}" for c in diag.get("conflicts", []))
    for f in current_findings(state):
        lines.append(
            f"Finding [{f['worker']}]: {f['category']} ({f['confidence']:.2f}, {f['status']}) - {f['root_cause']}"
        )
    results = state.get("step_results") or []
    if results:
        lines.extend(f"Step {r['index']}: {r['tool']} -> {r['status']}" for r in results)
    else:
        lines.append("Actions taken: none")
    lines.append(f"Next step: {next_step}")
    return "\n".join(lines)


def make_fallback_node(settings: Settings) -> Callable[[IncidentState], dict[str, Any]]:
    def fallback(state: IncidentState) -> dict[str, Any]:
        reason = escalation_reason(state, settings)
        summary = build_summary(state, reason)
        node_logger(__name__, state.get("incident_id", "?"), NODE).warning("escalating: %s", reason)
        escalation: Escalation = {"reason": reason, "summary": summary}
        return {
            "escalation": escalation,
            "status": IncidentStatus.ESCALATED.value,
            "pending_approval": None,
            "messages": [AIMessage(content=f"fallback: escalated ({reason})", name=NODE)],
            "node_log": [NODE],
        }

    return fallback

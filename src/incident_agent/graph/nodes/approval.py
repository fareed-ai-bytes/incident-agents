"""Approval request node: builds the pending approval (with before/after previews) for every
gated step. The graph is compiled with interrupt_before=["execute"], so it halts right after
this node until a human decision is recorded (BR-01)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from incident_agent.errors import ToolCallError
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import ApprovalItem, IncidentState, PendingApproval
from incident_agent.log import node_logger
from incident_agent.models import IncidentStatus
from incident_agent.policy.risk import gated_steps

NODE = "request_approval"


def approval_id(incident_id: str, round_no: int, step_index: int) -> str:
    return f"AP-{incident_id}-r{round_no}-s{step_index}"


def make_request_approval_node(
    rt: Runtime, on_request: Callable[[PendingApproval], None] | None = None
) -> Callable[[IncidentState], dict[str, Any]]:
    def request_approval(state: IncidentState) -> dict[str, Any]:
        log = node_logger(__name__, state["incident_id"], NODE)
        items: list[ApprovalItem] = []
        for step in gated_steps(state["plan"]):
            try:
                preview, _ = rt.call_tool(
                    "preview_write_action",
                    {"tool": step["tool"], "args": step["args"]},
                    state["incident_id"],
                )
                before, after = preview["before"], preview["after"]
            except ToolCallError as exc:
                log.warning("no preview for %s: %s", step["tool"], exc)
                before, after = [], []
            items.append(
                {
                    "approval_id": approval_id(
                        state["incident_id"], state.get("diagnosis_round", 1), step["index"]
                    ),
                    "step_index": step["index"],
                    "tool": step["tool"],
                    "args": step["args"],
                    "risk_tier": step["risk_tier"],
                    "rationale": step["rationale"],
                    "before": before,
                    "after": after,
                }
            )
        pending: PendingApproval = {
            "incident_id": state["incident_id"],
            "requested_at": rt.clock().isoformat(timespec="seconds"),
            "items": items,
        }
        if on_request is not None:
            on_request(pending)
        log.info("waiting for approval of %d step(s)", len(items))
        return {
            "pending_approval": pending,
            "status": IncidentStatus.PENDING_APPROVAL.value,
            "messages": [
                AIMessage(content=f"approval requested for {len(items)} step(s)", name=NODE)
            ],
            "node_log": [NODE],
        }

    return request_approval

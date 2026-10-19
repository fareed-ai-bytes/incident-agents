"""Human-in-the-loop decisions on a halted incident (S37).

The graph halts before `execute`. An ApprovalSession collects one decision per gated step,
writes them into the checkpointed state, and resumes the graph. Anything left undecided is
rejected: the safe default (design.md).
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any

from incident_agent.graph.state import ApprovalItem, IncidentState
from incident_agent.mcp_client.schema import validate_args
from incident_agent.models import ApprovalDecision
from incident_agent.policy.risk import requires_diff

if TYPE_CHECKING:
    from incident_agent.graph.runner import IncidentRunner

APPROVED = "approved"
REJECTED = "rejected"


class DecisionError(ValueError):
    """The decision cannot be accepted (no pending approval, bad args, missing approver...)."""


class DiffNotShownError(DecisionError):
    """A DESTRUCTIVE step was approved before its before/after diff was rendered (FR-08)."""


def diff_lines(item: ApprovalItem) -> list[str]:
    """Unified diff of the step's before/after preview (plain text, colour-free)."""
    diff = difflib.unified_diff(
        item.get("before", []), item.get("after", []), "before", "after", lineterm="", n=3
    )
    return list(diff) or ["(no change)"]


class ApprovalSession:
    def __init__(self, runner: IncidentRunner, incident_id: str, approver: str) -> None:
        if not approver.strip():
            raise DecisionError("an approver name is required")
        snap = runner.snapshot(incident_id)
        if tuple(snap.next) != ("execute",) or not snap.values.get("pending_approval"):
            raise DecisionError(f"incident {incident_id} has no pending approval")
        self.runner = runner
        self.incident_id = incident_id
        self.approver = approver
        self.values = snap.values
        self.pending = snap.values["pending_approval"]
        self.items: dict[int, ApprovalItem] = {
            i["step_index"]: dict(i) for i in self.pending["items"]
        }
        self.decisions: dict[int, ApprovalDecision] = {}
        self._diff_shown: set[int] = set()

    def item(self, step_index: int) -> ApprovalItem:
        try:
            return self.items[step_index]
        except KeyError:
            raise DecisionError(f"step {step_index} does not need approval") from None

    def validate_edit(self, step_index: int, args: Any) -> list[str]:
        spec = self.runner.tools.spec(self.item(step_index)["tool"])
        return validate_args(spec, args)

    def edit(self, step_index: int, args: dict[str, Any]) -> ApprovalItem:
        """Replace a step's args after validating them, and refresh its before/after preview."""
        errors = self.validate_edit(step_index, args)
        if errors:
            raise DecisionError("; ".join(errors))
        item = self.item(step_index)
        preview, _ = self.runner.runtime.call_tool(
            "preview_write_action", {"tool": item["tool"], "args": args}, self.incident_id
        )
        item.update(args=args, before=preview["before"], after=preview["after"])
        self._diff_shown.discard(step_index)  # the new diff must be shown before approval
        return item

    def render_diff(self, step_index: int) -> list[str]:
        """Return the diff for display and record that it was shown."""
        lines = diff_lines(self.item(step_index))
        self._diff_shown.add(step_index)
        return lines

    def diff_shown(self, step_index: int) -> bool:
        return step_index in self._diff_shown

    def decide(self, step_index: int, decision: str) -> None:
        if decision not in (APPROVED, REJECTED):
            raise DecisionError(f"unknown decision {decision!r}")
        item = self.item(step_index)
        if (
            decision == APPROVED
            and requires_diff(item["risk_tier"])
            and not self.diff_shown(step_index)
        ):
            raise DiffNotShownError(
                f"step {step_index + 1} ({item['tool']}) is DESTRUCTIVE: render its diff before approving"
            )
        self.decisions[step_index] = {
            "approval_id": item["approval_id"],
            "step_index": step_index,
            "decision": decision,
            "approver": self.approver,
            "decided_at": self.runner.runtime.clock().isoformat(timespec="seconds"),
            "args": item["args"],
        }

    def submit(self) -> IncidentState:
        for step_index in self.items:
            if step_index not in self.decisions:
                self.decide(step_index, REJECTED)  # safe default
        decisions = [self.decisions[i] for i in sorted(self.decisions)]
        self.runner.record_decisions(self.incident_id, decisions)
        return self.runner.resume(self.incident_id)

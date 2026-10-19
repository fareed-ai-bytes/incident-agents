"""Domain types shared across graph, agents, policy and CLI.

Graph state stores these as TypedDicts (plain, checkpoint-friendly); Pydantic models are used
where model output must be validated (planner, final answers).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict


class AlertType(StrEnum):
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    AUTH_FAILURE = "AUTH_FAILURE"
    WAREHOUSE_UNAVAILABLE = "WAREHOUSE_UNAVAILABLE"
    LATE_DATA = "LATE_DATA"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    UNKNOWN = "UNKNOWN"


class RiskTier(StrEnum):
    READ = "READ"
    REVERSIBLE = "REVERSIBLE"
    DESTRUCTIVE = "DESTRUCTIVE"


class IncidentStatus(StrEnum):
    TRIAGED = "TRIAGED"
    DIAGNOSING = "DIAGNOSING"
    PLANNED = "PLANNED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    EXECUTED = "EXECUTED"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


# Finding category for a worker that looked and found nothing wrong in its area.
NO_ISSUE = "NO_ISSUE"


class Alert(TypedDict):
    alert_id: str
    source: str
    pipeline: str
    severity: str
    summary: str
    message: str
    occurred_at: str


ALERT_REQUIRED_FIELDS = ("pipeline", "summary", "message")


class Finding(TypedDict):
    worker: str
    category: str  # an AlertType value, or NO_ISSUE
    root_cause: str
    evidence: list[str]
    confidence: float
    status: str  # complete | incomplete | failed
    round: int


class Diagnosis(TypedDict):
    category: str
    root_cause: str
    confidence: float
    conflicts: list[str]
    evidence: list[str]
    workers: list[str]


class PlanStep(TypedDict):
    index: int
    tool: str
    args: dict[str, Any]
    risk_tier: str
    rationale: str


class StepResult(TypedDict):
    index: int
    tool: str
    status: str  # SUCCEEDED | FAILED | SKIPPED
    output: Any
    attempts: int


class ApprovalDecision(TypedDict):
    approval_id: str
    step_index: int
    decision: str  # approved | rejected | expired
    approver: str
    decided_at: str
    args: dict[str, Any]

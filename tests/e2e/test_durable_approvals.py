"""Durable approvals across a restart (S39, automated part of the MANUAL check)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from incident_agent.graph.hitl import APPROVED, ApprovalSession
from incident_agent.graph.runner import IncidentRunner
from incident_agent.llm.heuristic import HeuristicModel
from incident_agent.mcp_client import ToolClient
from incident_agent.mcp_server.server import build_server
from incident_agent.mocks.job_runner import FakeJobRunner
from incident_agent.policy.approvals import ApprovalStore


def _process(settings, **kw):
    tools = ToolClient(build_server(settings))
    return IncidentRunner(settings, model=HeuristicModel(), tools=tools, **kw), tools


def _approve_everything(runner, incident_id):
    session = ApprovalSession(runner, incident_id, "ana")
    for idx in session.items:
        session.render_diff(idx)
        session.decide(idx, APPROVED)
    return session.submit()


def test_pending_approval_survives_restart_and_executes_exactly_once(seeded):
    first, tools = _process(seeded)
    incident = first.start("schema_drift")
    first.close()
    tools.close()  # the process is gone while the approval is pending

    store = ApprovalStore(seeded.audit_db)
    pending = store.rows(incident, status="PENDING")
    assert [r["tool"] for r in pending] == ["alter_table", "rerun_job"]

    second, tools = _process(seeded)
    assert second.pending_incidents() == [incident]
    final = _approve_everything(second, incident)
    assert final["status"] == "RESOLVED"
    second.close()
    tools.close()

    third, tools = _process(seeded)  # a later restart must not re-execute anything
    third.resume(incident)
    third.close()
    tools.close()

    rows = FakeJobRunner(seeded.audit_db).audit_rows(incident)
    assert [r["action"] for r in rows] == ["alter_table", "rerun_job"]  # one row each
    assert all(r["approver"] == "ana" for r in rows)
    assert {r["status"] for r in store.rows(incident)} == {"APPROVED"}
    assert store.pending_incidents() == []


def test_pending_approvals_listed_oldest_first_across_incidents(seeded):
    runner, tools = _process(seeded)
    a = runner.start("auth_failure")
    b = runner.start("late_data")
    assert runner.pending_incidents() == [a, b]
    runner.close()
    tools.close()


def test_expired_approval_escalates_and_writes_nothing(seeded):
    runner, tools = _process(seeded)
    incident = runner.start("warehouse_unavailable")
    runner.close()
    tools.close()

    later = datetime.now(UTC) + timedelta(hours=seeded.approval_ttl_hours + 1)
    late, tools = _process(seeded, clock=lambda: later)
    final = _approve_everything(late, incident)
    late.close()
    tools.close()
    assert final["status"] == "ESCALATED"
    assert final["escalation"]["reason"] == "approval_expired"
    assert FakeJobRunner(seeded.audit_db).audit_rows(incident) == []
    assert {r["status"] for r in ApprovalStore(seeded.audit_db).rows(incident)} == {"EXPIRED"}

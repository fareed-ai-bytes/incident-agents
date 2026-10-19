"""Executor (S29)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from incident_agent.graph.nodes.approval import make_request_approval_node
from incident_agent.graph.nodes.executor import make_execute_node
from incident_agent.graph.state import initial_state
from incident_agent.mocks.fixtures import load_alert
from incident_agent.mocks.job_runner import FakeJobRunner

PIPE = "orders_warehouse_load"


def _step(i, tool, args, tier):
    return {"index": i, "tool": tool, "args": args, "risk_tier": tier, "rationale": ""}


def _state(plan, **extra):
    return {
        **initial_state("INC-X", "warehouse_unavailable", load_alert("warehouse_unavailable")),
        "diagnosis_round": 1,
        "plan": plan,
        **extra,
    }


def _approve_all(runtime, state, approver="ana", decision="approved"):
    pending = make_request_approval_node(runtime)(state)["pending_approval"]
    approvals = [
        {
            "approval_id": item["approval_id"],
            "step_index": item["step_index"],
            "decision": decision,
            "approver": approver,
            "decided_at": "2026-10-19T00:00:00+00:00",
            "args": item["args"],
        }
        for item in pending["items"]
    ]
    return {**state, "pending_approval": pending, "approvals": approvals}


def _audit(settings):
    return FakeJobRunner(settings.audit_db).audit_rows("INC-X")


WRITE_PLAN = [
    _step(0, "resume_warehouse", {"warehouse_name": "LOAD_WH"}, "REVERSIBLE"),
    _step(1, "rerun_job", {"pipeline": PIPE}, "REVERSIBLE"),
    _step(2, "check_pipeline_health", {"pipeline": PIPE}, "READ"),
]


def test_read_only_plan_runs_without_approval(runtime):
    plan = [_step(0, "get_job_status", {"pipeline": PIPE}, "READ")]
    out = make_execute_node(runtime, "execute_auto")(_state(plan))
    assert out["execution_status"] == "SUCCEEDED"
    assert out["step_results"][0]["output"]["status"] == "FAILED"  # job status, not step status


def test_approved_plan_runs_in_order_and_records_approver(runtime, seeded):
    state = _approve_all(runtime, _state(WRITE_PLAN))
    out = make_execute_node(runtime, "execute")(state)
    assert out["execution_status"] == "SUCCEEDED"
    assert [r["tool"] for r in out["step_results"]] == [s["tool"] for s in WRITE_PLAN]
    assert out["step_results"][2]["output"]["healthy"] is True
    rows = _audit(seeded)
    assert [(r["action"], r["approver"]) for r in rows] == [
        ("resume_warehouse", "ana"),
        ("rerun_job", "ana"),
    ]


def test_failed_step_stops_later_steps(runtime, seeded):
    plan = [
        _step(0, "resume_warehouse", {"warehouse_name": "LOAD_WH"}, "REVERSIBLE"),
        _step(1, "get_pipeline_info", {"pipeline": "does_not_exist"}, "READ"),
        _step(2, "rerun_job", {"pipeline": PIPE}, "REVERSIBLE"),
    ]
    out = make_execute_node(runtime, "execute")(_approve_all(runtime, _state(plan)))
    assert out["execution_status"] == "FAILED"
    assert [r["status"] for r in out["step_results"]] == ["SUCCEEDED", "FAILED"]
    assert [r["action"] for r in _audit(seeded)] == ["resume_warehouse"]  # rerun_job never ran


def test_rejected_approval_runs_nothing(runtime, seeded):
    state = _approve_all(runtime, _state(WRITE_PLAN), decision="rejected")
    out = make_execute_node(runtime, "execute")(state)
    assert out["execution_status"] == "REJECTED" and out["step_results"] == []
    assert _audit(seeded) == []


def test_missing_approval_runs_nothing(runtime, seeded):
    state = _state(WRITE_PLAN)
    state["pending_approval"] = make_request_approval_node(runtime)(state)["pending_approval"]
    out = make_execute_node(runtime, "execute")(state)
    assert out["execution_status"] == "REJECTED"
    assert _audit(seeded) == []


def test_expired_approval_runs_nothing(runtime, seeded):
    state = _approve_all(runtime, _state(WRITE_PLAN))
    later = datetime.now(UTC) + timedelta(hours=runtime.settings.approval_ttl_hours + 1)
    rt = dataclasses.replace(runtime, clock=lambda: later)
    out = make_execute_node(rt, "execute")(state)
    assert out["execution_status"] == "EXPIRED"
    assert _audit(seeded) == []


def test_edited_args_from_approval_are_used(runtime, seeded):
    state = _approve_all(runtime, _state(WRITE_PLAN[:1]))
    state["approvals"][0]["args"] = {"warehouse_name": "TRANSFORM_WH"}
    make_execute_node(runtime, "execute")(state)
    assert _audit(seeded)[0]["args"] == {"warehouse_name": "TRANSFORM_WH"}


def test_transient_read_step_is_retried(runtime):
    plan = [_step(0, "get_job_status", {"pipeline": "inventory_glue_job"}, "READ")]
    out = make_execute_node(runtime, "execute_auto")(_state(plan))
    assert out["execution_status"] == "SUCCEEDED"
    assert out["step_results"][0]["attempts"] == 3
    assert out["retry_counts"] == {"execute_auto.get_job_status": 2}

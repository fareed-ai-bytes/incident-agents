"""Risk-tier policy (S36): one case per tier (BR-01)."""

from __future__ import annotations

import pytest

from incident_agent.graph.nodes.approval import make_request_approval_node
from incident_agent.graph.routing import EXECUTE_AUTO, REQUEST_APPROVAL, route_after_plan
from incident_agent.graph.state import initial_state
from incident_agent.mocks.fixtures import load_alert
from incident_agent.models import RiskTier
from incident_agent.policy.risk import gated_steps, requires_approval, requires_diff, stricter


def _step(i, tool, args, tier):
    return {"index": i, "tool": tool, "args": args, "risk_tier": tier, "rationale": ""}


def _state(plan):
    return {
        **initial_state("INC-POL", "late_data", load_alert("late_data")),
        "diagnosis_round": 1,
        "plan": plan,
    }


def test_read_tier_auto_runs_and_never_creates_an_approval_request(runtime):
    assert not requires_approval("READ") and not requires_diff("READ")
    plan = [
        _step(
            0,
            "check_partition_arrival",
            {"table": "events_daily", "partition": "dt=2026-10-18"},
            "READ",
        )
    ]
    assert route_after_plan({"plan": plan}) == EXECUTE_AUTO
    assert gated_steps(plan) == []
    # Even if the gate node ran on a mixed plan, READ steps never become approval items.
    mixed = plan + [_step(1, "rerun_job", {"pipeline": "events_daily_partition"}, "REVERSIBLE")]
    items = make_request_approval_node(runtime)(_state(mixed))["pending_approval"]["items"]
    assert [i["tool"] for i in items] == ["rerun_job"]


def test_reversible_tier_needs_one_approval_no_diff_required():
    assert requires_approval("REVERSIBLE") and not requires_diff("REVERSIBLE")
    plan = [_step(0, "rerun_job", {"pipeline": "p"}, "REVERSIBLE")]
    assert route_after_plan({"plan": plan}) == REQUEST_APPROVAL


def test_destructive_tier_needs_approval_with_diff(runtime):
    assert requires_approval("DESTRUCTIVE") and requires_diff("DESTRUCTIVE")
    plan = [
        _step(
            0,
            "backfill_partition",
            {"table": "events_daily", "partition": "dt=2026-10-18"},
            "DESTRUCTIVE",
        )
    ]
    assert route_after_plan({"plan": plan}) == REQUEST_APPROVAL
    [item] = make_request_approval_node(runtime)(_state(plan))["pending_approval"]["items"]
    assert item["before"] and item["after"] and item["before"] != item["after"]


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("READ", "REVERSIBLE", RiskTier.REVERSIBLE),
        ("DESTRUCTIVE", "READ", RiskTier.DESTRUCTIVE),
        ("REVERSIBLE", "REVERSIBLE", RiskTier.REVERSIBLE),
    ],
)
def test_stricter(a, b, expected):
    assert stricter(a, b) is expected

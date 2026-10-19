"""Supervisor routing (S20), fallback routing (S21). One test per routing-table row and branch."""

from __future__ import annotations

import pytest

from incident_agent.graph.routing import (
    FALLBACK,
    LOG_ANALYST,
    ROUTING_TABLE,
    SCHEMA_INSPECTOR,
    SUPERVISOR,
    WAREHOUSE_AGENT,
    WORKERS,
    route_after_triage,
    route_to_workers,
    supervisor,
)
from incident_agent.graph.state import initial_state
from incident_agent.models import AlertType


def _routed(alert_type):
    state = {**initial_state("INC-R", "x", {"pipeline": "p"}), "alert_type": alert_type}
    assert route_after_triage(state) == SUPERVISOR
    state = {**state, **{k: v for k, v in supervisor(state).items() if k != "messages"}}
    sends = route_to_workers(state)
    return [s.node for s in sends], sends


def test_routing_table_covers_every_known_type():
    assert set(ROUTING_TABLE) == set(AlertType) - {AlertType.UNKNOWN}


def test_route_schema_drift():
    targets, _ = _routed("SCHEMA_DRIFT")
    assert targets == [LOG_ANALYST, SCHEMA_INSPECTOR]


def test_route_auth_failure():
    targets, _ = _routed("AUTH_FAILURE")
    assert targets == [LOG_ANALYST]


def test_route_warehouse_unavailable():
    targets, _ = _routed("WAREHOUSE_UNAVAILABLE")
    assert targets == [WAREHOUSE_AGENT, LOG_ANALYST]


def test_route_late_data():
    targets, _ = _routed("LATE_DATA")
    assert targets == [WAREHOUSE_AGENT, LOG_ANALYST]


def test_route_transient_network():
    targets, _ = _routed("TRANSIENT_NETWORK")
    assert targets == [LOG_ANALYST]


@pytest.mark.parametrize("alert_type", [t.value for t in ROUTING_TABLE])
def test_workers_outside_the_row_are_never_sent(alert_type):
    targets, _ = _routed(alert_type)
    not_in_row = set(WORKERS) - set(ROUTING_TABLE[AlertType(alert_type)])
    assert not (set(targets) & not_in_row)


def test_send_payload_is_scoped_worker_input():
    _, sends = _routed("SCHEMA_DRIFT")
    assert set(sends[0].arg) == {"incident_id", "alert", "alert_type", "diagnosis_round"}
    assert sends[0].arg["diagnosis_round"] == 1


def test_unknown_alert_routes_to_fallback():
    state = {**initial_state("INC-R", "x", {}), "alert_type": "UNKNOWN"}
    assert route_after_triage(state) == FALLBACK
    assert route_after_triage({**state, "alert_type": "GARBAGE"}) == FALLBACK


def _diag(category="SCHEMA_DRIFT", confidence=0.9):
    return {
        "category": category,
        "root_cause": "r",
        "confidence": confidence,
        "conflicts": [],
        "evidence": [],
        "workers": [],
    }


def test_route_after_aggregate_confident_goes_to_planner():
    from incident_agent.graph.routing import PLANNER, make_route_after_aggregate

    route = make_route_after_aggregate(0.6)
    assert route({"diagnosis": _diag(confidence=0.6)}) == PLANNER


def test_low_confidence_routes_to_fallback():
    from incident_agent.graph.routing import make_route_after_aggregate

    route = make_route_after_aggregate(0.6)
    assert route({"diagnosis": _diag(confidence=0.4)}) == FALLBACK
    assert route({"diagnosis": _diag(category="UNKNOWN")}) == FALLBACK
    assert route({"diagnosis": None}) == FALLBACK


def test_fallback_produces_human_readable_summary(settings):
    from incident_agent.graph.nodes.fallback import make_fallback_node

    state = {
        **initial_state("INC-F", "schema_drift", {"pipeline": "p", "summary": "s", "message": "m"}),
        "alert_type": "SCHEMA_DRIFT",
        "diagnosis_round": 1,
        "diagnosis": {**_diag(confidence=0.4), "conflicts": ["log_analyst vs schema_inspector"]},
        "findings": [
            {
                "worker": "log_analyst",
                "category": "SCHEMA_DRIFT",
                "root_cause": "column added",
                "evidence": [],
                "confidence": 0.8,
                "status": "complete",
                "round": 1,
            }
        ],
    }
    out = make_fallback_node(settings)(state)
    esc = out["escalation"]
    assert out["status"] == "ESCALATED" and esc["reason"] == "low_confidence"
    text = esc["summary"]
    assert text.startswith("ESCALATED:")
    for needle in (
        "INC-F",
        "confidence 0.40",
        "Conflict: log_analyst vs schema_inspector",
        "Finding [log_analyst]",
        "Next step:",
    ):
        assert needle in text, needle


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"alert_type": "UNKNOWN"}, "unknown_alert"),
        ({"alert_type": "SCHEMA_DRIFT", "plan_error": "bad"}, "planner_failed"),
        ({"alert_type": "SCHEMA_DRIFT", "execution_status": "REJECTED"}, "approval_rejected"),
        ({"alert_type": "SCHEMA_DRIFT", "execution_status": "EXPIRED"}, "approval_expired"),
        ({"alert_type": "SCHEMA_DRIFT", "execution_status": "FAILED"}, "execution_failed"),
        ({"alert_type": "SCHEMA_DRIFT", "verify_attempts": 2, "healthy": False}, "verify_failed"),
    ],
)
def test_fallback_reason_per_dead_end(patch, reason, settings):
    from incident_agent.graph.nodes.fallback import make_fallback_node

    state = {**initial_state("INC-F", "x", {}), **patch}
    out = make_fallback_node(settings)(state)
    assert out["escalation"]["reason"] == reason
    assert out["escalation"]["summary"]


def _plan(*tiers):
    return [
        {"index": i, "tool": "t", "args": {}, "risk_tier": t, "rationale": ""}
        for i, t in enumerate(tiers)
    ]


def test_route_after_plan_branches():
    from incident_agent.graph.routing import EXECUTE_AUTO, REQUEST_APPROVAL, route_after_plan

    assert route_after_plan({"plan": _plan("READ", "READ")}) == EXECUTE_AUTO
    assert route_after_plan({"plan": _plan("READ", "REVERSIBLE")}) == REQUEST_APPROVAL
    assert route_after_plan({"plan": _plan("DESTRUCTIVE")}) == REQUEST_APPROVAL
    assert route_after_plan({"plan": []}) == FALLBACK
    assert route_after_plan({"plan": _plan("READ"), "plan_error": "x"}) == FALLBACK


def test_route_after_execute_branches():
    from incident_agent.graph.routing import VERIFY, route_after_execute

    assert route_after_execute({"execution_status": "SUCCEEDED"}) == VERIFY
    for status in ("FAILED", "REJECTED", "EXPIRED", ""):
        assert route_after_execute({"execution_status": status}) == FALLBACK

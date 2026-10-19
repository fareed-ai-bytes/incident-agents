"""Verify loop (S30)."""

from __future__ import annotations

import dataclasses

from incident_agent.graph.builder import build_graph
from incident_agent.graph.nodes.verify import make_route_after_verify
from incident_agent.graph.state import initial_state
from incident_agent.mocks.fixtures import load_alert


def _run(runtime, scenario_id="transient_network"):
    graph = build_graph(runtime)
    return graph.invoke(initial_state("INC-V", scenario_id, load_alert(scenario_id)))


def test_verify_healthy_ends_resolved(runtime):
    out = _run(runtime)
    assert out["status"] == "RESOLVED" and out["healthy"] is True
    assert out["verify_attempts"] == 1
    assert out["escalation"] is None


def test_verify_failure_loops_back_once_then_escalates(runtime):
    calls = []

    def never_healthy(pipeline, incident_id):
        calls.append(pipeline)
        return {"healthy": False, "missing_fixes": ["magic"]}

    out = _run(dataclasses.replace(runtime, health_check=never_healthy))
    assert out["verify_attempts"] == 2 <= runtime.settings.max_verify_attempts  # BR-06
    assert len(calls) == 2
    assert out["node_log"].count("supervisor") == 2  # exactly one re-diagnosis
    assert out["diagnosis_round"] == 2
    assert out["status"] == "ESCALATED"
    assert out["escalation"]["reason"] == "verify_failed"


def test_route_after_verify_branches():
    route = make_route_after_verify(2)
    assert route({"healthy": True, "verify_attempts": 1}) == "__end__"
    assert route({"healthy": False, "verify_attempts": 1}) == "supervisor"
    assert route({"healthy": False, "verify_attempts": 2}) == "fallback"

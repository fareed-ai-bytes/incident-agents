"""IncidentState reducers (S18) and parallel fan-out merge (S25)."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from incident_agent.graph.state import (
    IncidentState,
    current_findings,
    initial_state,
    max_counts,
    sum_counts,
)


def _finding(worker, rnd=1, category="SCHEMA_DRIFT"):
    return {
        "worker": worker,
        "category": category,
        "root_cause": "r",
        "evidence": [],
        "confidence": 0.8,
        "status": "complete",
        "round": rnd,
    }


def test_count_reducers():
    assert sum_counts({"a": 1}, {"a": 2, "b": 1}) == {"a": 3, "b": 1}
    assert max_counts({"a": 5}, {"a": 2, "b": 9}) == {"a": 5, "b": 9}
    assert sum_counts(None, None) == {}


def test_findings_reducer_appends_through_a_graph():
    def node_a(state):
        return {"findings": [_finding("a")]}

    def node_b(state):
        return {"findings": [_finding("b")]}

    g = StateGraph(IncidentState)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_edge(START, "a")
    g.add_edge("a", "b")
    g.add_edge("b", END)
    out = g.compile().invoke(initial_state("INC-1", "schema_drift", {}))
    assert [f["worker"] for f in out["findings"]] == ["a", "b"]


def test_current_findings_filters_by_round():
    state = {"diagnosis_round": 2, "findings": [_finding("a", 1), _finding("b", 2)]}
    assert [f["worker"] for f in current_findings(state)] == ["b"]


def test_messages_reducer_is_add_messages():
    hints = IncidentState.__annotations__
    assert "add_messages" in str(hints["messages"])
    assert "operator.add" in str(hints["findings"]) or "add" in str(hints["findings"])

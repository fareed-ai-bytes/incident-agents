"""The top-level StateGraph compiles and has the documented shape (S18, S25)."""

from __future__ import annotations


def test_graph_compiles_with_expected_nodes(runtime):
    from incident_agent.graph.builder import build_graph

    graph = build_graph(runtime)
    nodes = set(graph.get_graph().nodes)
    for name in (
        "triage",
        "supervisor",
        "log_analyst",
        "schema_inspector",
        "warehouse_agent",
        "aggregate",
        "fallback",
    ):
        assert name in nodes, name

"""The top-level StateGraph: triage -> diagnose (parallel workers) -> aggregate -> ...

See docs/architecture.md for the diagram. Every node transition is checkpointed when a
checkpointer is supplied.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from incident_agent.graph.nodes.aggregate import aggregate
from incident_agent.graph.nodes.fallback import make_fallback_node
from incident_agent.graph.nodes.triage import make_triage_node
from incident_agent.graph.nodes.workers import make_worker_nodes
from incident_agent.graph.routing import (
    FALLBACK,
    PLANNER,
    SUPERVISOR,
    WORKERS,
    make_route_after_aggregate,
    route_after_triage,
    route_to_workers,
    supervisor,
)
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import IncidentState


def build_graph(rt: Runtime, checkpointer: Any = None, interrupt_before: list[str] | None = None):
    g = StateGraph(IncidentState)
    g.add_node("triage", make_triage_node(rt))
    g.add_node(SUPERVISOR, supervisor)
    for name, node in make_worker_nodes(rt).items():
        g.add_node(name, node)
    g.add_node("aggregate", aggregate)
    g.add_node(FALLBACK, make_fallback_node(rt.settings))

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage, [SUPERVISOR, FALLBACK])
    g.add_conditional_edges(SUPERVISOR, route_to_workers, list(WORKERS))
    for worker in WORKERS:
        g.add_edge(worker, "aggregate")
    g.add_conditional_edges(
        "aggregate",
        make_route_after_aggregate(rt.settings.confidence_threshold),
        {PLANNER: END, FALLBACK: FALLBACK},
    )
    g.add_edge(FALLBACK, END)
    return g.compile(checkpointer=checkpointer, interrupt_before=interrupt_before or [])

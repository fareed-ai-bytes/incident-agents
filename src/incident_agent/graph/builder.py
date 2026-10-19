"""The top-level StateGraph: triage -> diagnose (parallel workers) -> aggregate -> ...

See docs/architecture.md for the diagram. Every node transition is checkpointed when a
checkpointer is supplied.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from incident_agent.graph.nodes.aggregate import aggregate
from incident_agent.graph.nodes.approval import make_request_approval_node
from incident_agent.graph.nodes.executor import make_execute_node
from incident_agent.graph.nodes.fallback import make_fallback_node
from incident_agent.graph.nodes.planner import make_planner_node
from incident_agent.graph.nodes.triage import make_triage_node
from incident_agent.graph.nodes.workers import make_worker_nodes
from incident_agent.graph.routing import (
    EXECUTE,
    EXECUTE_AUTO,
    FALLBACK,
    PLANNER,
    REQUEST_APPROVAL,
    SUPERVISOR,
    WORKERS,
    make_route_after_aggregate,
    route_after_execute,
    route_after_plan,
    route_after_triage,
    route_to_workers,
    supervisor,
)
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import IncidentState


def build_graph(
    rt: Runtime,
    checkpointer: Any = None,
    interrupt_before: list[str] | None = None,
    on_approval_request: Any = None,
):
    """Compile the graph. It always halts before `execute` (the approval gate) unless a test
    passes interrupt_before explicitly."""
    g = StateGraph(IncidentState)
    g.add_node("triage", make_triage_node(rt))
    g.add_node(SUPERVISOR, supervisor)
    for name, node in make_worker_nodes(rt).items():
        g.add_node(name, node)
    g.add_node("aggregate", aggregate)
    g.add_node(PLANNER, make_planner_node(rt))
    g.add_node(REQUEST_APPROVAL, make_request_approval_node(rt, on_approval_request))
    g.add_node(EXECUTE, make_execute_node(rt, EXECUTE))
    g.add_node(EXECUTE_AUTO, make_execute_node(rt, EXECUTE_AUTO))
    g.add_node(FALLBACK, make_fallback_node(rt.settings))

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage, [SUPERVISOR, FALLBACK])
    g.add_conditional_edges(SUPERVISOR, route_to_workers, list(WORKERS))
    for worker in WORKERS:
        g.add_edge(worker, "aggregate")
    g.add_conditional_edges(
        "aggregate",
        make_route_after_aggregate(rt.settings.confidence_threshold),
        [PLANNER, FALLBACK],
    )
    g.add_conditional_edges(PLANNER, route_after_plan, [REQUEST_APPROVAL, EXECUTE_AUTO, FALLBACK])
    g.add_edge(REQUEST_APPROVAL, EXECUTE)
    for node in (EXECUTE, EXECUTE_AUTO):
        g.add_conditional_edges(node, route_after_execute, {"verify": END, FALLBACK: FALLBACK})
    g.add_edge(FALLBACK, END)
    gate = [EXECUTE] if interrupt_before is None else interrupt_before
    return g.compile(checkpointer=checkpointer, interrupt_before=gate)

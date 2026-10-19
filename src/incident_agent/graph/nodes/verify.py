"""Verify node (S30): is the pipeline healthy after remediation? (FR-12)

healthy -> END; failing the first time -> back to the supervisor for one re-diagnosis;
failing again -> fallback (BR-06).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from incident_agent.errors import ToolCallError
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import IncidentState
from incident_agent.log import node_logger
from incident_agent.models import IncidentStatus

NODE = "verify"


def make_verify_node(rt: Runtime) -> Callable[[IncidentState], dict[str, Any]]:
    def verify(state: IncidentState) -> dict[str, Any]:
        incident_id = state["incident_id"]
        pipeline = state["alert"]["pipeline"]
        log = node_logger(__name__, incident_id, NODE)
        attempts = state.get("verify_attempts", 0) + 1
        try:
            if rt.health_check is not None:
                health = rt.health_check(pipeline, incident_id)
            else:
                health, _ = rt.call_tool(
                    "check_pipeline_health", {"pipeline": pipeline}, incident_id
                )
            healthy = bool(health.get("healthy"))
            detail = f"missing fixes: {health.get('missing_fixes')}" if not healthy else "healthy"
        except ToolCallError as exc:
            log.warning("health check failed: %s", exc)
            healthy, detail = False, f"health check failed: {exc}"
        log.info("attempt %d: %s", attempts, detail)
        update: dict[str, Any] = {
            "verify_attempts": attempts,
            "healthy": healthy,
            "messages": [AIMessage(content=f"verify #{attempts}: {detail}", name=NODE)],
            "node_log": [NODE],
        }
        if healthy:
            update["status"] = IncidentStatus.RESOLVED.value
        return update

    return verify


def make_route_after_verify(max_attempts: int) -> Callable[[IncidentState], str]:
    from incident_agent.graph.routing import FALLBACK, SUPERVISOR

    def route_after_verify(state: IncidentState) -> str:
        if state.get("healthy"):
            return "__end__"
        return SUPERVISOR if state.get("verify_attempts", 0) < max_attempts else FALLBACK

    return route_after_verify

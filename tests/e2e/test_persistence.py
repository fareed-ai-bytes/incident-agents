"""Resume after a process restart (S32)."""

from __future__ import annotations

from incident_agent.graph.runner import IncidentRunner
from incident_agent.llm.heuristic import HeuristicModel
from incident_agent.mcp_client import ToolClient
from incident_agent.mcp_server.server import build_server


class SimulatedKill(BaseException):
    """Like Ctrl+C / SIGKILL: not an Exception, so nothing in the app catches it."""


class DiesInLogAnalyst(HeuristicModel):
    def chat(self, messages, tools=None, *, purpose=""):
        if purpose == "log_analyst":
            raise SimulatedKill()
        return super().chat(messages, tools, purpose=purpose)


def _process(settings, model):
    """A fresh 'process': its own MCP session, model and SQLite connection."""
    tools = ToolClient(build_server(settings))
    return IncidentRunner(settings, model=model, tools=tools), tools


def test_resume_after_process_restart(seeded):
    from incident_agent.mocks.injector import inject

    incident_id, alert = inject("transient_network")

    first, tools = _process(seeded, DiesInLogAnalyst())
    try:
        first.start_alert(incident_id, "transient_network", alert)
        raise AssertionError("the simulated kill should have stopped the run")
    except SimulatedKill:
        pass
    snap = first.snapshot(incident_id)
    assert snap.next == ("log_analyst",)  # died mid-diagnosis
    first.close()
    tools.close()

    second, tools = _process(seeded, HeuristicModel())
    try:
        final = second.resume(incident_id)
    finally:
        second.close()
        tools.close()

    assert final["status"] == "RESOLVED"
    log = final["node_log"]
    # Completed nodes were not repeated after the restart.
    assert log.count("triage") == 1
    assert log.count("supervisor") == 1
    assert log.count("log_analyst") == 1
    assert log[:2] == ["triage", "supervisor"]

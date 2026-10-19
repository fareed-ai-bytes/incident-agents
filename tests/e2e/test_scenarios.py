"""End-to-end: all five scenarios through the full graph (S41).

Diagnosis uses the offline heuristic model here (CI). verification.md S41 requires a final
run with the real local model: set RUN_REAL_MODEL=1 (and MODEL_NAME) to run
`test_scenario_with_real_model`, which is skipped otherwise.
"""

from __future__ import annotations

import os

import pytest

from incident_agent.graph.hitl import APPROVED, ApprovalSession
from incident_agent.graph.runner import IncidentRunner
from incident_agent.llm.heuristic import HeuristicModel
from incident_agent.mocks.job_runner import FakeJobRunner
from incident_agent.mocks.scenarios import SCENARIOS

EXPECTED_FIXES = {
    "schema_drift": ["alter_table", "rerun_job"],
    "auth_failure": ["rotate_credentials", "rerun_job"],
    "warehouse_unavailable": ["resume_warehouse", "rerun_job"],
    "late_data": ["backfill_partition"],
    "transient_network": [],
}


def stub_approver(runner: IncidentRunner, incident_id: str, name: str = "e2e-approver"):
    """Approves every gated step after rendering its diff. Lives only in tests/ (design.md)."""
    session = ApprovalSession(runner, incident_id, name)
    for idx in session.items:
        session.render_diff(idx)
        session.decide(idx, APPROVED)
    return session.submit()


def run_to_end(runner: IncidentRunner, scenario_id: str):
    incident = runner.start(scenario_id)
    values = runner.snapshot(incident).values
    approvals = 0
    while values.get("pending_approval"):
        approvals += 1
        values = stub_approver(runner, incident)
    return incident, values, approvals


@pytest.fixture
def runner(seeded, client):
    with IncidentRunner(seeded, model=HeuristicModel(), tools=client) as r:
        yield r


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_scenario_reaches_correct_root_cause_and_resolves(scenario_id, runner, seeded):
    incident, values, _ = run_to_end(runner, scenario_id)
    s = SCENARIOS[scenario_id]
    assert values["alert_type"] == s.expected_alert_type
    assert values["diagnosis"]["category"] == s.expected_alert_type
    assert values["status"] == "RESOLVED", values.get("escalation")
    rows = FakeJobRunner(seeded.audit_db).audit_rows(incident)
    assert [r["action"] for r in rows] == EXPECTED_FIXES[scenario_id]
    # Success metric: no write without a recorded approver for gated tiers.
    assert all(r["approver"] for r in rows if r["risk_tier"] != "READ")


def test_transient_network_resolves_without_human(runner, seeded):
    incident, values, approvals = run_to_end(runner, "transient_network")
    assert approvals == 0  # never stopped at the gate
    assert values["status"] == "RESOLVED"
    assert "request_approval" not in values["node_log"]
    assert values["retry_counts"].get("execute_auto.get_job_status") == 2  # BR-04 did the work
    assert FakeJobRunner(seeded.audit_db).audit_rows(incident) == []


def test_malformed_alert_escalates(runner):
    from incident_agent.mocks.injector import new_incident_id

    incident = new_incident_id("malformed")
    values = runner.start_alert(incident, "malformed", {"source": "scheduler"})
    assert values["alert_type"] == "UNKNOWN" and values["status"] == "ESCALATED"
    assert values["escalation"]["reason"] == "unknown_alert"


@pytest.mark.real_model
@pytest.mark.skipif(os.environ.get("RUN_REAL_MODEL") != "1", reason="needs a local Ollama model")
@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_scenario_with_real_model(scenario_id, seeded, client):
    import dataclasses

    from incident_agent.llm.ollama import OllamaChatModel

    settings = dataclasses.replace(
        seeded,
        model_provider="ollama",
        model_name=os.environ.get("MODEL_NAME", seeded.model_name),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", seeded.ollama_base_url),
    )
    model = OllamaChatModel(settings.model_name, settings.ollama_base_url)
    with IncidentRunner(settings, model=model, tools=client) as runner:
        _, values, _ = run_to_end(runner, scenario_id)
    assert values["diagnosis"]["category"] == SCENARIOS[scenario_id].expected_alert_type

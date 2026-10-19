"""Schema Inspector (S22) and Warehouse Agent (S23)."""

from __future__ import annotations

import pytest

from incident_agent.mocks.fixtures import load_alert
from incident_agent.mocks.scenarios import SCENARIOS
from incident_agent.raw_loop.retry import RetryPolicy

POLICY = RetryPolicy(3, 0.0)


def _schema(client, scenario_id):
    from incident_agent.agents.schema_inspector import ALLOWED_TOOLS, run_schema_inspector

    finding, _ = run_schema_inspector(
        client.scoped(ALLOWED_TOOLS), load_alert(scenario_id), "INC-W", POLICY
    )
    return finding


def test_schema_inspector_detects_drift(client):
    f = _schema(client, "schema_drift")
    assert f["category"] == "SCHEMA_DRIFT" and f["confidence"] >= 0.8
    assert any("loyalty_tier" in e for e in f["evidence"])
    assert "loyalty_tier" in f["root_cause"]


@pytest.mark.parametrize("scenario_id", [s for s in SCENARIOS if s != "schema_drift"])
def test_schema_inspector_reports_no_drift_on_other_scenarios(scenario_id, client):
    f = _schema(client, scenario_id)
    assert f["category"] == "NO_ISSUE", f


def test_schema_inspector_tool_failure_is_failed_finding(client):
    from incident_agent.agents.schema_inspector import ALLOWED_TOOLS, run_schema_inspector

    alert = {**load_alert("schema_drift"), "pipeline": "no_such_pipeline"}
    f, _ = run_schema_inspector(client.scoped(ALLOWED_TOOLS), alert, "INC-W", POLICY)
    assert f["status"] == "failed" and f["confidence"] == 0.0

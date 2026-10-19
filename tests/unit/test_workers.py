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


def _warehouse(client, scenario_id):
    from incident_agent.agents.warehouse_agent import ALLOWED_TOOLS, run_warehouse_agent

    finding, _ = run_warehouse_agent(
        client.scoped(ALLOWED_TOOLS), load_alert(scenario_id), "INC-W", POLICY
    )
    return finding


def test_warehouse_agent_detects_suspended_warehouse(client):
    f = _warehouse(client, "warehouse_unavailable")
    assert f["category"] == "WAREHOUSE_UNAVAILABLE" and f["confidence"] >= 0.8
    assert any("LOAD_WH state=SUSPENDED" in e for e in f["evidence"])


def test_warehouse_agent_detects_late_partition(client):
    f = _warehouse(client, "late_data")
    assert f["category"] == "LATE_DATA"
    assert any("arrived=False" in e for e in f["evidence"])


def test_warehouse_agent_no_suspended_false_positive_on_late_data(client):
    f = _warehouse(client, "late_data")
    assert f["category"] != "WAREHOUSE_UNAVAILABLE"
    assert not any("SUSPENDED" in e for e in f["evidence"])


@pytest.mark.parametrize("scenario_id", ["schema_drift", "auth_failure", "transient_network"])
def test_warehouse_agent_no_issue_elsewhere(scenario_id, client):
    assert _warehouse(client, scenario_id)["category"] == "NO_ISSUE"

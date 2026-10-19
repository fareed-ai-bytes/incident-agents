"""Remediation planner (S28)."""

from __future__ import annotations

import dataclasses
import json

import pytest
from helpers import ScriptedModel, text_reply

from incident_agent.graph.nodes.planner import make_planner_node, validate_plan
from incident_agent.graph.state import initial_state
from incident_agent.mocks.fixtures import load_alert
from incident_agent.mocks.scenarios import SCENARIOS


def _state(scenario_id, category=None):
    s = SCENARIOS[scenario_id]
    return {
        **initial_state("INC-PL", scenario_id, load_alert(scenario_id)),
        "alert_type": s.expected_alert_type,
        "diagnosis": {
            "category": category or s.expected_alert_type,
            "root_cause": "r",
            "confidence": 0.9,
            "conflicts": [],
            "evidence": [],
            "workers": [],
        },
    }


def test_plan_has_ordered_steps_with_risk_tier(runtime):
    out = make_planner_node(runtime)(_state("schema_drift"))
    plan = out["plan"]
    assert out["plan_error"] == "" and out["status"] == "PLANNED"
    assert [s["index"] for s in plan] == list(range(len(plan)))
    assert [s["tool"] for s in plan] == ["alter_table", "rerun_job", "check_pipeline_health"]
    assert [s["risk_tier"] for s in plan] == ["DESTRUCTIVE", "REVERSIBLE", "READ"]
    assert plan[0]["args"] == {
        "table": "crm_customers",
        "add_columns": [{"name": "loyalty_tier", "type": "VARCHAR"}],
    }


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_every_scenario_gets_a_valid_plan_ending_in_a_read_check(scenario_id, runtime):
    plan = make_planner_node(runtime)(_state(scenario_id))["plan"]
    assert plan and plan[-1]["risk_tier"] == "READ"


def test_planner_cannot_downgrade_a_tools_declared_tier(runtime):
    raw = {
        "steps": [
            {"tool": "alter_table", "args": {"table": "t", "add_columns": []}, "risk_tier": "READ"},
            {"tool": "get_job_status", "args": {"pipeline": "p"}, "risk_tier": "DESTRUCTIVE"},
        ]
    }
    plan, errors = validate_plan(raw, runtime)
    assert errors == []
    assert plan[0]["risk_tier"] == "DESTRUCTIVE"  # downgrade ignored
    assert plan[1]["risk_tier"] == "DESTRUCTIVE"  # stricter is allowed


def test_invalid_plans_are_rejected(runtime):
    cases = [
        {"steps": []},
        {"steps": [{"tool": "drop_database", "args": {}}]},
        {"steps": [{"tool": "search_logs", "args": {"pipeline": "p", "pattern": "x"}}]},
        {"steps": [{"tool": "alter_table", "args": {"table": "t"}}]},
        {"nope": 1},
    ]
    for raw in cases:
        plan, errors = validate_plan(raw, runtime)
        assert errors, raw


def test_executor_injected_args_are_stripped(runtime):
    raw = {"steps": [{"tool": "rerun_job", "args": {"pipeline": "p", "approver": "me"}}]}
    plan, errors = validate_plan(raw, runtime)
    assert errors == [] and plan[0]["args"] == {"pipeline": "p"}


def test_invalid_plan_is_reprompted_then_plan_error(runtime):
    model = ScriptedModel([text_reply("here is my plan: do stuff")])
    rt = dataclasses.replace(runtime, model=model)
    out = make_planner_node(rt)(_state("auth_failure"))
    assert out["plan"] == [] and out["plan_error"]
    assert len(model.calls) == runtime.settings.max_reprompts + 1


def test_planner_recovers_after_one_bad_reply(runtime):
    good = {"steps": [{"tool": "check_pipeline_health", "args": {"pipeline": "p"}}]}
    model = ScriptedModel([text_reply("{bad"), text_reply(json.dumps(good))])
    rt = dataclasses.replace(runtime, model=model)
    out = make_planner_node(rt)(_state("auth_failure"))
    assert out["plan_error"] == "" and out["reprompt_counts"] == {"planner": 1}

"""Triage node (S19)."""

from __future__ import annotations

import dataclasses

import pytest
from helpers import ScriptedModel, text_reply

from incident_agent.graph.nodes.triage import make_triage_node, parse_alert_type
from incident_agent.graph.state import initial_state
from incident_agent.mocks.fixtures import load_alert
from incident_agent.mocks.scenarios import SCENARIOS


def _state(alert):
    return initial_state("INC-T", "x", alert)


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_triage_classifies_all_scenario_alerts(scenario_id, runtime):
    out = make_triage_node(runtime)(_state(load_alert(scenario_id)))
    assert out["alert_type"] == SCENARIOS[scenario_id].expected_alert_type
    assert out["node_log"] == ["triage"]


@pytest.mark.parametrize(
    "alert",
    [
        None,
        {},
        {"pipeline": "crm_customers_sync"},
        {"pipeline": "", "summary": "x", "message": "y"},
        {"pipeline": 3, "summary": "x", "message": "y"},
    ],
)
def test_malformed_alert_yields_unknown_without_model_call(alert, runtime):
    model = ScriptedModel([text_reply('{"alert_type": "SCHEMA_DRIFT"}')])
    rt = dataclasses.replace(runtime, model=model)
    out = make_triage_node(rt)(_state(alert))
    assert out["alert_type"] == "UNKNOWN"
    assert model.calls == []


def test_unparseable_model_output_is_reprompted_then_unknown(runtime):
    model = ScriptedModel([text_reply("I think it is schema drift!")])
    rt = dataclasses.replace(runtime, model=model)
    out = make_triage_node(rt)(_state(load_alert("schema_drift")))
    assert out["alert_type"] == "UNKNOWN"
    assert len(model.calls) == runtime.settings.max_reprompts + 1
    assert out["reprompt_counts"]["triage"] == runtime.settings.max_reprompts + 1


def test_model_guessing_an_invalid_type_is_not_accepted(runtime):
    model = ScriptedModel(
        [text_reply('{"alert_type": "DISK_FULL"}'), text_reply('{"alert_type": "LATE_DATA"}')]
    )
    rt = dataclasses.replace(runtime, model=model)
    out = make_triage_node(rt)(_state(load_alert("late_data")))
    assert out["alert_type"] == "LATE_DATA" and out["reprompt_counts"] == {"triage": 1}


def test_parse_alert_type_tolerates_code_fences():
    assert parse_alert_type('```json\n{"alert_type": "auth_failure"}\n```') == "AUTH_FAILURE"
    assert parse_alert_type("nope") is None

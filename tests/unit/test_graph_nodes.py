"""Graph nodes return dict updates and never mutate their input (S18, S24)."""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

from helpers import ScriptedModel

from incident_agent.graph.nodes.workers import make_worker_nodes
from incident_agent.graph.routing import LOG_ANALYST
from incident_agent.mocks.fixtures import load_alert


def freeze(value):
    """Deep read-only view: any mutation attempt inside a node raises TypeError/AttributeError."""
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def _input(scenario_id="schema_drift", alert_type="SCHEMA_DRIFT"):
    return {
        "incident_id": "INC-N",
        "alert": load_alert(scenario_id),
        "alert_type": alert_type,
        "diagnosis_round": 1,
    }


def test_log_analyst_node_wraps_raw_loop(runtime):
    out = make_worker_nodes(runtime)[LOG_ANALYST](freeze(_input()))
    assert isinstance(out, dict)
    [finding] = out["findings"]
    assert finding["worker"] == LOG_ANALYST and finding["category"] == "SCHEMA_DRIFT"
    assert finding["round"] == 1
    assert out["node_log"] == [LOG_ANALYST]
    assert out["token_usage"][LOG_ANALYST] > 0


def test_log_analyst_node_model_failure_becomes_failed_finding(runtime):
    from incident_agent.llm.base import ModelError

    class Down(ScriptedModel):
        def chat(self, *a, **k):
            raise ModelError("ollama down")

    rt = dataclasses.replace(runtime, model=Down([]))
    out = make_worker_nodes(rt)[LOG_ANALYST](freeze(_input()))
    assert out["findings"][0]["status"] == "failed"
    assert out["findings"][0]["confidence"] == 0.0


def test_every_worker_node_returns_dict_from_frozen_input(runtime):
    for name, node in make_worker_nodes(runtime).items():
        out = node(freeze(_input("warehouse_unavailable", "WAREHOUSE_UNAVAILABLE")))
        assert isinstance(out, dict), name
        assert len(out["findings"]) == 1, name

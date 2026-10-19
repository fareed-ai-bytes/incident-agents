"""Log Analyst worker (S17). Stubbed models prove the plumbing; real-model runs are MANUAL."""

from __future__ import annotations

import pytest
from helpers import ScriptedModel, tool_call

from incident_agent.agents.log_analyst import ALLOWED_TOOLS, run_log_analyst
from incident_agent.llm.heuristic import HeuristicModel
from incident_agent.mocks.fixtures import load_alert
from incident_agent.mocks.scenarios import SCENARIOS


def _analyse(model, client, settings, scenario_id="schema_drift"):
    alert = load_alert(scenario_id)
    tools = client.scoped(ALLOWED_TOOLS)
    return run_log_analyst(
        model, tools, alert, SCENARIOS[scenario_id].expected_alert_type, "INC-LA", settings
    )


def test_log_analyst_finds_root_cause_schema_drift(client, seeded):
    """Scripted ReAct trace: search -> narrow to a window -> conclude with cited evidence."""
    model = ScriptedModel(
        [
            tool_call("search_logs", {"pipeline": "crm_customers_sync", "pattern": "ERROR"}),
            tool_call(
                "fetch_log_window", {"pipeline": "crm_customers_sync", "offset": 870, "limit": 8}
            ),
            tool_call(
                "final_answer",
                {
                    "root_cause": "source added column loyalty_tier missing in warehouse",
                    "category": "SCHEMA_DRIFT",
                    "evidence": ["L874: column loyalty_tier not found in target table"],
                    "confidence": 0.9,
                },
            ),
        ]
    )
    analysis = _analyse(model, client, seeded)
    f = analysis.finding
    assert f["category"] == "SCHEMA_DRIFT" and f["status"] == "complete"
    assert f["confidence"] == 0.9 and f["evidence"][0].startswith("L874")
    # Observations really came from the MCP tools.
    window = analysis.loop.steps[1].observation
    assert "loyalty_tier" in window and '"line": 874' in window


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_log_analyst_heuristic_model_all_scenarios(scenario_id, client, seeded):
    analysis = _analyse(HeuristicModel(), client, seeded, scenario_id)
    f = analysis.finding
    s = SCENARIOS[scenario_id]
    assert f["category"] == s.expected_alert_type, f
    assert any(e.startswith(f"L{s.root_cause_line}:") for e in f["evidence"]), f["evidence"]
    assert analysis.loop.iterations <= seeded.max_iterations


def test_log_analyst_incomplete_returns_partial_finding_with_zero_confidence(client, seeded):
    model = ScriptedModel(
        [tool_call("search_logs", {"pipeline": "crm_customers_sync", "pattern": "INFO"})]
    )
    f = _analyse(model, client, seeded).finding
    assert f["status"] == "incomplete" and f["confidence"] == 0.0
    assert f["category"] == "UNKNOWN"


def test_log_analyst_unknown_category_is_normalised(client, seeded):
    model = ScriptedModel(
        [
            tool_call(
                "final_answer",
                {"root_cause": "x", "category": "ALIENS", "evidence": [], "confidence": 7},
            )
        ]
    )
    f = _analyse(model, client, seeded).finding
    assert f["category"] == "UNKNOWN" and f["confidence"] == 1.0


def test_log_analyst_cannot_reach_tools_outside_allow_list(client, seeded):
    model = ScriptedModel([tool_call("rerun_job", {"pipeline": "crm_customers_sync"})])
    analysis = _analyse(model, client, seeded)
    # rerun_job is not offered to the model, so the call is malformed and never executed.
    assert analysis.loop.status == "failed"
    assert analysis.loop.steps == []

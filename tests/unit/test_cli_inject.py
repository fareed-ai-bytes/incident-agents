import json

import pytest

from incident_agent.cli.main import main
from incident_agent.mocks.scenarios import SCENARIOS


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_inject_prints_alert_for_each_scenario(scenario_id, capsys):
    assert main(["inject", "--scenario", scenario_id]) == 0
    out = capsys.readouterr().out
    header, body = out.split("\n", 1)
    assert header.startswith(f"[OK] Injected {scenario_id} as INC-{scenario_id}-")
    assert json.loads(body)["pipeline"] == SCENARIOS[scenario_id].pipeline


def test_inject_unknown_scenario_exits_non_zero_with_message(capsys):
    assert main(["inject", "--scenario", "bogus"]) != 0
    assert "unknown scenario 'bogus'" in capsys.readouterr().err


def test_incident_ids_are_unique():
    from incident_agent.mocks.injector import inject

    assert inject("late_data")[0] != inject("late_data")[0]

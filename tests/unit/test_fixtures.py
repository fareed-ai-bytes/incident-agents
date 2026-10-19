import json

import pytest

from incident_agent.mocks import fixtures, fixtures_gen
from incident_agent.mocks.scenarios import SCENARIOS, UnknownScenarioError, get_scenario

# Generous context budget for a 7-14B local model (tokens ~ chars / 4).
CONTEXT_BUDGET_TOKENS = 32_000


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_fixture_contains_root_cause_signal_not_at_edges(scenario_id):
    s = SCENARIOS[scenario_id]
    lines = s.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == s.log_lines
    assert s.root_cause_text in lines[s.root_cause_line - 1]
    assert 1 < s.root_cause_line < len(lines)
    assert s.root_cause_text not in lines[0] and s.root_cause_text not in lines[-1]


def test_at_least_one_fixture_exceeds_context_budget():
    sizes = {s.id: len(s.log_path.read_text(encoding="utf-8")) // 4 for s in SCENARIOS.values()}
    assert max(sizes.values()) > CONTEXT_BUDGET_TOKENS, sizes


def test_fixtures_are_reproducible_from_generator(tmp_path):
    fixtures_gen.generate(tmp_path)
    for s in SCENARIOS.values():
        for name in ("pipeline.log", "alert.json", "source_schema.json"):
            committed = _norm((s.fixture_dir / name).read_text(encoding="utf-8"))
            fresh = _norm((tmp_path / s.id / name).read_text(encoding="utf-8"))
            assert committed == fresh, f"{s.id}/{name} differs from generator output"


def test_alert_fixtures_are_valid_json_with_pipeline():
    for s in SCENARIOS.values():
        alert = json.loads((s.fixture_dir / "alert.json").read_text(encoding="utf-8"))
        assert alert["pipeline"] == s.pipeline
        assert alert["message"]


def test_schema_drift_source_has_extra_column_others_match():
    drift = fixtures.source_schema("crm_customers_sync")
    assert "loyalty_tier" in [c["name"] for c in drift["columns"]]
    other = fixtures.source_schema("orders_warehouse_load")
    assert "loyalty_tier" not in [c["name"] for c in other["columns"]]


def test_log_window_and_search():
    win = fixtures.log_window("crm_customers_sync", 870, 10)
    assert [w["line"] for w in win] == list(range(870, 880))
    hits = fixtures.search_log("crm_customers_sync", "loyalty_tier")
    assert any(h["line"] == 874 for h in hits)


def test_unknown_scenario():
    with pytest.raises(UnknownScenarioError, match="choose one of"):
        get_scenario("nope")

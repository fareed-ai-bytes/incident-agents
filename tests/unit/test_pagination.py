"""Paginated log fetching on the oversized fixture (S35, automated part)."""

from __future__ import annotations

from incident_agent.agents.log_analyst import ALLOWED_TOOLS, run_log_analyst
from incident_agent.llm.heuristic import HeuristicModel
from incident_agent.mocks.fixtures import load_alert
from incident_agent.mocks.scenarios import SCENARIOS
from incident_agent.policy.budgets import budget_for
from incident_agent.raw_loop.tokens import estimate_tokens


def test_oversized_log_is_read_in_pages_within_budget(client, seeded):
    s = SCENARIOS["late_data"]
    whole_log_tokens = estimate_tokens(s.log_path.read_text(encoding="utf-8"))
    assert whole_log_tokens > 10 * budget_for("log_analyst")

    analysis = run_log_analyst(
        HeuristicModel(),
        client.scoped(ALLOWED_TOOLS),
        load_alert("late_data"),
        "LATE_DATA",
        "INC-PG",
        seeded,
    )
    assert analysis.finding["category"] == "LATE_DATA"
    fetches = [st for st in analysis.loop.steps if st.tool == "fetch_log_window"]
    assert fetches and all(st.args["limit"] <= seeded.log_page_size for st in fetches)
    assert analysis.loop.max_prompt_tokens <= budget_for("log_analyst")

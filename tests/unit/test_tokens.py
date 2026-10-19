"""Token budgets (S33): an over-budget prompt is trimmed or refused, never sent."""

from __future__ import annotations

import pytest
from helpers import ScriptedModel, tool_call

from incident_agent.policy.budgets import MODEL_CONTEXT_TOKENS, NODE_BUDGETS
from incident_agent.raw_loop import LoopTool, run_react_loop
from incident_agent.raw_loop.tokens import (
    TRIM_MARKER,
    TokenBudgetExceededError,
    estimate_messages,
    estimate_tokens,
    fit_to_budget,
)


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_budgets_fit_the_model_context():
    assert all(0 < b < MODEL_CONTEXT_TOKENS for b in NODE_BUDGETS.values())


def test_prompt_within_budget_is_unchanged():
    msgs = [{"role": "user", "content": "hello"}]
    assert fit_to_budget(msgs, 100) == msgs


def test_over_budget_prompt_trims_tool_observations_oldest_first():
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "task"},
        {"role": "tool", "content": "A" * 4000},
        {"role": "tool", "content": "B" * 400},
    ]
    out = fit_to_budget(msgs, 400)
    assert estimate_messages(out) <= 400
    assert out[2]["content"].endswith(TRIM_MARKER)
    assert out[3]["content"] == "B" * 400  # newest observation kept verbatim
    assert msgs[2]["content"] == "A" * 4000  # input not mutated


def test_prompt_that_cannot_fit_is_refused():
    with pytest.raises(TokenBudgetExceededError):
        fit_to_budget([{"role": "user", "content": "x" * 10_000}], 100)


def test_loop_never_sends_an_over_budget_prompt():
    seen = []

    class Recorder(ScriptedModel):
        def chat(self, messages, tools=None, *, purpose=""):
            seen.append(estimate_messages(messages, tools))
            return super().chat(messages, tools, purpose=purpose)

    big = LoopTool("dump", "d", {"type": "object", "properties": {}}, lambda a: "Z" * 3000)
    model = Recorder([tool_call("dump", {})])
    res = run_react_loop(
        model,
        [big],
        system="s",
        task="t",
        final_parameters={"type": "object", "properties": {}},
        max_iterations=5,
        token_budget=1500,
    )
    assert res.status == "incomplete"
    assert max(seen) <= 1500
    assert res.max_prompt_tokens <= 1500


def test_loop_fails_cleanly_when_even_the_task_is_over_budget():
    model = ScriptedModel([tool_call("final_answer", {})])
    res = run_react_loop(
        model,
        [],
        system="s" * 8000,
        task="t",
        final_parameters={"type": "object"},
        token_budget=100,
    )
    assert res.status == "failed" and "budget" in res.error
    assert model.calls == []  # never sent

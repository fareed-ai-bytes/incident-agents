"""Sliding-window memory (S34)."""

from __future__ import annotations

import json

from helpers import ScriptedModel, tool_call

from incident_agent.raw_loop import LoopTool, run_react_loop
from incident_agent.raw_loop.memory import SUMMARY_PREFIX, SlidingWindow


def _page(offset):
    lines = [{"line": offset + i, "text": f"INFO noise {offset + i}"} for i in range(5)]
    if offset == 1:
        lines[2] = {"line": 3, "text": "ERROR [loader] column loyalty_tier not found"}
    return {"lines": lines}


def test_old_observations_summarised_not_dropped():
    tool = LoopTool(
        "fetch_log_window",
        "page",
        {"type": "object", "properties": {"offset": {"type": "integer"}}, "required": ["offset"]},
        lambda a: _page(a["offset"]),
    )
    model = ScriptedModel(
        [tool_call("fetch_log_window", {"offset": o}) for o in (1, 6, 11, 16, 21)]
        + [tool_call("final_answer", {})]
    )
    memory = SlidingWindow(window=2)
    res = run_react_loop(
        model,
        [tool],
        system="s",
        task="t",
        final_parameters={"type": "object"},
        transcript=memory,
        max_iterations=6,
    )
    assert res.status == "complete"
    # Only the last 2 exchanges are verbatim...
    assert len(memory.exchanges) == 2
    last_prompt = model.calls[-1]
    verbatim = [m for m in last_prompt if m["role"] == "tool"]
    assert len(verbatim) == 2
    # ...but the early ERROR line (step 1) is still findable in the summary note.
    assert "column loyalty_tier not found" in res.summary_note
    assert '"line": 3' in res.summary_note
    summary_msgs = [m for m in last_prompt if m["content"].startswith(SUMMARY_PREFIX)]
    assert len(summary_msgs) == 1 and "loyalty_tier" in summary_msgs[0]["content"]


def test_window_smaller_than_history_bounds_prompt_growth():
    memory = SlidingWindow(window=1)
    for i in range(10):
        memory.add("c", "search_logs", {"i": i}, "", json.dumps({"x": "y" * 500}))
    msgs = memory.build("sys", "task")
    assert len([m for m in msgs if m["role"] == "tool"]) == 1
    assert len(memory.summary_note.splitlines()) <= 30


def test_summary_without_signals_keeps_a_snippet():
    memory = SlidingWindow(window=1)
    memory.add("c", "get_pipeline_info", {"pipeline": "p"}, "", '{"table": "orders"}')
    memory.add("c", "get_pipeline_info", {"pipeline": "q"}, "", '{"table": "x"}')
    assert 'get_pipeline_info({"pipeline": "p"}): {"table": "orders"}' in memory.summary_note

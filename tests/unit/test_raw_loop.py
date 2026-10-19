"""Raw ReAct loop (S13), max_iterations guard (S14), malformed tool-call re-prompts (S15)."""

from __future__ import annotations

import re
from pathlib import Path

from helpers import ScriptedModel, text_reply, tool_call

from incident_agent.raw_loop import LoopTool, run_react_loop

FINAL_PARAMS = {
    "type": "object",
    "properties": {"root_cause": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["root_cause", "confidence"],
}


def _echo_tool(log: list):
    def fn(args):
        log.append(args)
        return {"lines": [f"line {args['offset']}: ERROR boom"]}

    return LoopTool(
        "fetch",
        "fetch lines",
        {"type": "object", "properties": {"offset": {"type": "integer"}}, "required": ["offset"]},
        fn,
    )


def _run(model, tools, **kw):
    return run_react_loop(
        model, tools, system="sys", task="find it", final_parameters=FINAL_PARAMS, **kw
    )


# -- S13 --------------------------------------------------------------------------------------


def test_raw_loop_reason_act_observe_then_final_answer():
    calls = []
    model = ScriptedModel(
        [
            tool_call("fetch", {"offset": 1}, thought="look at the start"),
            tool_call("fetch", {"offset": 100}, thought="narrow down"),
            tool_call("final_answer", {"root_cause": "boom", "confidence": 0.9}),
        ]
    )
    res = _run(model, [_echo_tool(calls)])
    assert res.status == "complete"
    assert res.answer == {"root_cause": "boom", "confidence": 0.9}
    assert [s.args["offset"] for s in res.steps] == [1, 100]
    assert res.steps[1].thought == "narrow down"
    # The second model call saw the first observation (observe -> reason).
    second_prompt = model.calls[1]
    assert any(m["role"] == "tool" and "ERROR boom" in m["content"] for m in second_prompt)


def test_raw_loop_tool_error_becomes_observation_not_crash():
    from incident_agent.errors import PermanentToolError

    def broken(_args):
        raise PermanentToolError("table not found")

    tool = LoopTool("fetch", "x", {"type": "object", "properties": {}}, broken)
    model = ScriptedModel(
        [tool_call("fetch", {}), tool_call("final_answer", {"root_cause": "r", "confidence": 0.1})]
    )
    res = _run(model, [tool])
    assert res.status == "complete"
    assert res.steps[0].error.startswith("permanent")
    assert "table not found" in res.steps[0].observation


def test_raw_loop_accepts_tool_call_written_as_json_content():
    model = ScriptedModel(
        [text_reply('{"name": "final_answer", "arguments": {"root_cause": "r", "confidence": 1}}')]
    )
    assert _run(model, []).status == "complete"


def test_raw_loop_has_no_framework_imports():
    import incident_agent.raw_loop as pkg

    pattern = re.compile(r"^\s*(from|import)\s+(langgraph|langchain)", re.MULTILINE)
    for path in Path(pkg.__file__).parent.rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path


# -- S14 --------------------------------------------------------------------------------------


def test_raw_loop_respects_max_iterations():
    calls = []
    model = ScriptedModel([tool_call("fetch", {"offset": 1})])  # never concludes
    res = _run(model, [_echo_tool(calls)], max_iterations=6)
    assert res.status == "incomplete"  # returned, not raised (BR-02)
    assert res.answer is None
    assert res.iterations == 6
    assert len(calls) == 6 and len(model.calls) == 6


# -- S15 --------------------------------------------------------------------------------------


def test_malformed_tool_call_reprompted():
    """Bad JSON twice, then a valid call: the step succeeds after 2 re-prompts (BR-05)."""
    model = ScriptedModel(
        [
            tool_call("final_answer", '{"root_cause": "boom", "confid'),
            tool_call("final_answer", "not json at all"),
            tool_call("final_answer", {"root_cause": "boom", "confidence": 0.8}),
        ]
    )
    res = _run(model, [], max_reprompts=2)
    assert res.status == "complete"
    assert res.reprompts == 2
    # The re-prompt told the model what was wrong.
    correction = model.calls[1][-1]
    assert correction["role"] == "user" and "not valid JSON" in correction["content"]


def test_third_consecutive_malformed_call_fails_the_step():
    model = ScriptedModel([tool_call("final_answer", "{bad")])
    res = _run(model, [], max_reprompts=2)
    assert res.status == "failed"
    assert res.reprompts == 3
    assert len(model.calls) == 3  # original + 2 re-prompts, never a 4th call
    assert "re-prompts" in res.error


def test_reprompt_budget_resets_per_step():
    calls = []
    model = ScriptedModel(
        [
            tool_call("fetch", "{bad"),
            tool_call("fetch", {"offset": 1}),
            tool_call("nope", {}),
            tool_call("final_answer", {"root_cause": "x"}),  # missing confidence
            tool_call("final_answer", {"root_cause": "x", "confidence": 0.7}),
        ]
    )
    res = _run(model, [_echo_tool(calls)], max_reprompts=2)
    assert res.status == "complete"
    assert res.reprompts == 3


def test_corrections_do_not_leak_into_later_steps():
    calls = []
    model = ScriptedModel(
        [
            tool_call("fetch", "{bad"),
            tool_call("fetch", {"offset": 1}),
            tool_call("final_answer", {"root_cause": "x", "confidence": 0.7}),
        ]
    )
    _run(model, [_echo_tool(calls)])
    last_prompt = model.calls[-1]
    assert not any("not a valid tool call" in (m.get("content") or "") for m in last_prompt)

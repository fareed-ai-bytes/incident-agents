"""Framework-free Reason-Act-Observe loop against any local chat model.

No LangGraph / LangChain imports in this package (enforced by a test). The loop:
  1. sends the transcript plus tool schemas to the model,
  2. parses one tool call (re-prompting when it is malformed, BR-05),
  3. runs the tool and appends the observation,
  4. stops on `final_answer`, or at `max_iterations` with status "incomplete" (BR-02).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from incident_agent.errors import ToolCallError
from incident_agent.llm.base import ChatMessage, ChatModel, ToolSchema, tool_schema
from incident_agent.log import get_logger
from incident_agent.raw_loop.memory import Transcript
from incident_agent.raw_loop.tokens import estimate_messages

log = get_logger(__name__)

FINAL_TOOL = "final_answer"
MAX_OBSERVATION_CHARS = 4000

LoopStatus = Literal["complete", "incomplete", "failed"]


@dataclass(frozen=True)
class LoopTool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[[dict[str, Any]], Any]

    def schema(self) -> ToolSchema:
        return tool_schema(self.name, self.description, self.parameters)


@dataclass
class Step:
    iteration: int
    thought: str
    tool: str
    args: dict[str, Any]
    observation: str
    error: str | None = None


@dataclass
class LoopResult:
    status: LoopStatus
    answer: dict[str, Any] | None
    steps: list[Step] = field(default_factory=list)
    iterations: int = 0
    reprompts: int = 0
    error: str | None = None
    summary_note: str = ""
    max_prompt_tokens: int = 0


@dataclass(frozen=True)
class Action:
    call_id: str
    name: str
    args: dict[str, Any]
    raw: ChatMessage


class MalformedActionError(ValueError):
    """The model's reply is not one valid tool call."""


def parse_action(msg: ChatMessage, schemas: dict[str, dict[str, Any]]) -> Action:
    """Extract exactly one valid tool call from a model reply, or raise MalformedActionError."""
    calls = msg.get("tool_calls") or []
    if calls:
        call = calls[0]
        name, raw_args, call_id = (
            call["function"]["name"],
            call["function"]["arguments"],
            call["id"],
        )
    else:
        # Small local models often write the call as JSON in the content instead.
        try:
            obj = json.loads((msg.get("content") or "").strip())
        except ValueError:
            raise MalformedActionError("reply contained no tool call") from None
        if not isinstance(obj, dict) or "name" not in obj:
            raise MalformedActionError("reply contained no tool call")
        name, raw_args, call_id = obj["name"], obj.get("arguments", {}), "content_call"
    if name not in schemas:
        raise MalformedActionError(f"unknown tool {name!r}; available: {', '.join(schemas)}")
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except ValueError as exc:
            raise MalformedActionError(f"arguments for {name} are not valid JSON: {exc}") from None
    else:
        args = raw_args
    if not isinstance(args, dict):
        raise MalformedActionError(f"arguments for {name} must be a JSON object")
    missing = [r for r in schemas[name].get("required", []) if r not in args]
    if missing:
        raise MalformedActionError(f"{name} is missing required arguments: {', '.join(missing)}")
    return Action(call_id=call_id, name=name, args=args, raw=msg)


def _observe(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > MAX_OBSERVATION_CHARS:
        text = (
            text[:MAX_OBSERVATION_CHARS]
            + f"... [truncated {len(text) - MAX_OBSERVATION_CHARS} chars]"
        )
    return text


def run_react_loop(
    model: ChatModel,
    tools: list[LoopTool],
    *,
    system: str,
    task: str,
    final_parameters: dict[str, Any],
    max_iterations: int = 6,
    max_reprompts: int = 2,
    transcript: Transcript | None = None,
    purpose: str = "react",
) -> LoopResult:
    """Run the loop. Never raises for model or tool misbehaviour: the status says what happened."""
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")
    by_name = {t.name: t for t in tools}
    schemas = {t.name: t.parameters for t in tools}
    schemas[FINAL_TOOL] = final_parameters
    tool_schemas = [t.schema() for t in tools] + [
        tool_schema(FINAL_TOOL, "Report the root cause when you are confident.", final_parameters)
    ]
    memory = transcript or Transcript()
    result = LoopResult(status="incomplete", answer=None)

    for iteration in range(1, max_iterations + 1):
        result.iterations = iteration
        corrections: list[ChatMessage] = []
        step_reprompts = 0
        while True:
            messages = memory.build(system, task) + corrections
            result.max_prompt_tokens = max(
                result.max_prompt_tokens, estimate_messages(messages, tool_schemas)
            )
            reply = model.chat(messages, tool_schemas, purpose=purpose)
            try:
                action = parse_action(reply, schemas)
                break
            except MalformedActionError as problem:
                step_reprompts += 1
                result.reprompts += 1
                log.info("%s: malformed tool call (%d): %s", purpose, step_reprompts, problem)
                if step_reprompts > max_reprompts:
                    result.status = "failed"
                    result.error = (
                        f"malformed tool call after {max_reprompts} re-prompts: {problem}"
                    )
                    result.summary_note = memory.summary_note
                    return result
                corrections = [
                    {"role": "assistant", "content": reply.get("content") or "(empty)"},
                    {
                        "role": "user",
                        "content": f"Your previous reply was not a valid tool call: {problem}. "
                        "Reply with exactly one tool call using the provided tools.",
                    },
                ]

        thought = (reply.get("content") or "").strip()
        if action.name == FINAL_TOOL:
            result.status = "complete"
            result.answer = action.args
            result.summary_note = memory.summary_note
            return result

        error = None
        try:
            observation = _observe(by_name[action.name].fn(action.args))
        except ToolCallError as exc:
            error = f"{exc.kind} error: {exc}"
            observation = f"ERROR ({exc.kind}): {exc}"
            log.info("%s: tool %s failed: %s", purpose, action.name, exc)
        step = Step(iteration, thought, action.name, action.args, observation, error)
        result.steps.append(step)
        memory.add(action.call_id, action.name, action.args, thought, observation)

    result.summary_note = memory.summary_note
    return result

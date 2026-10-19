"""Remediation planner (S28): an ordered, schema-valid plan with risk tiers (FR-06).

The model proposes steps; this node validates them against the discovered MCP tool schemas
and stamps each step with the tool's DECLARED risk tier. A model-supplied tier can only make
a step stricter, never looser (verification.md S28).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field, ValidationError

from incident_agent.agents.prompts import planner as prompts
from incident_agent.errors import ToolCallError
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import IncidentState
from incident_agent.llm.base import ChatMessage
from incident_agent.log import node_logger
from incident_agent.mcp_client.schema import model_parameters, validate_args
from incident_agent.models import AlertType, IncidentStatus, PlanStep, RiskTier
from incident_agent.policy.budgets import budget_for
from incident_agent.policy.risk import stricter
from incident_agent.raw_loop.tokens import estimate_messages, fit_to_budget

NODE = "planner"
MAX_STEPS = 6
# Tools a plan may use: everything except log reading and the approval-time preview.
EXCLUDED_TOOLS = frozenset({"search_logs", "fetch_log_window", "preview_write_action"})


class StepModel(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    risk_tier: str | None = None


class PlanModel(BaseModel):
    steps: list[StepModel] = Field(min_length=1, max_length=MAX_STEPS)


def _extract_json(text: str) -> Any:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("no JSON object in reply")
    return json.loads(match.group(0))


def validate_plan(raw: Any, rt: Runtime, log: Any = None) -> tuple[list[PlanStep], list[str]]:
    """Return (plan, errors). The plan is only usable when errors is empty."""
    try:
        model = PlanModel.model_validate(raw)
    except ValidationError as exc:
        return [], [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
    specs = rt.tools.discover()
    errors: list[str] = []
    plan: list[PlanStep] = []
    for i, step in enumerate(model.steps):
        spec = specs.get(step.tool)
        if spec is None or step.tool in EXCLUDED_TOOLS:
            errors.append(f"step {i}: tool {step.tool!r} is not available to the planner")
            continue
        errors += [f"step {i} ({step.tool}): {e}" for e in validate_args(spec, step.args)]
        tier = spec.risk_tier
        if step.risk_tier:
            try:
                claimed = RiskTier(step.risk_tier.upper())
            except ValueError:
                claimed = tier
            if stricter(claimed, tier) is not tier and log is not None:
                log.info("step %d: model asked for stricter tier %s than %s", i, claimed, tier)
            elif claimed is not tier and log is not None:
                log.warning(
                    "step %d: planner tried to downgrade %s to %s; kept %s", i, tier, claimed, tier
                )
            tier = stricter(claimed, tier)
        args = {
            k: v
            for k, v in step.args.items()
            if k not in ("incident_id", "approver", "approval_id", "step_index")
        }
        plan.append(
            {
                "index": i,
                "tool": step.tool,
                "args": args,
                "risk_tier": tier.value,
                "rationale": step.rationale,
            }
        )
    return plan, errors


def planner_tools(rt: Runtime) -> list[dict[str, Any]]:
    out = []
    for spec in rt.tools.discover().values():
        if spec.name in EXCLUDED_TOOLS:
            continue
        params = model_parameters(spec)
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "risk_tier": spec.risk_tier.value,
                "properties": params["properties"],
                "required": params["required"],
            }
        )
    return out


def gather_context(rt: Runtime, state: IncidentState) -> dict[str, Any]:
    """READ-only facts the planner needs (table names, drifted columns...)."""
    pipeline = state["alert"]["pipeline"]
    incident_id = state["incident_id"]
    context: dict[str, Any] = {"incident_id": incident_id}
    try:
        context["pipeline_info"], _ = rt.call_tool(
            "get_pipeline_info", {"pipeline": pipeline}, incident_id
        )
        if state["diagnosis"]["category"] == AlertType.SCHEMA_DRIFT.value:
            context["schema_diff"], _ = rt.call_tool(
                "compare_source_schema", {"pipeline": pipeline}, incident_id
            )
    except ToolCallError as exc:
        context["context_error"] = str(exc)
    return context


def make_planner_node(rt: Runtime) -> Callable[[IncidentState], dict[str, Any]]:
    def planner(state: IncidentState) -> dict[str, Any]:
        log = node_logger(__name__, state["incident_id"], NODE)
        diagnosis = state["diagnosis"]
        context = gather_context(rt, state)
        messages: list[ChatMessage] = [
            {"role": "system", "content": prompts.system_prompt(planner_tools(rt))},
            {"role": "user", "content": prompts.user_prompt(dict(diagnosis), context)},
        ]
        plan: list[PlanStep] = []
        errors: list[str] = ["no attempt"]
        reprompts = 0
        tokens = 0
        for attempt in range(rt.settings.max_reprompts + 1):
            messages = fit_to_budget(messages, budget_for(NODE))  # raises if over
            tokens = max(tokens, estimate_messages(messages))
            reply = rt.model.chat(messages, purpose=NODE)
            try:
                plan, errors = validate_plan(_extract_json(reply.get("content", "")), rt, log)
            except ValueError as exc:
                plan, errors = [], [f"reply is not JSON: {exc}"]
            if not errors:
                break
            reprompts = attempt + 1
            log.info("invalid plan (attempt %d): %s", attempt + 1, errors)
            messages = [
                *messages,
                {"role": "assistant", "content": reply.get("content", "")},
                {"role": "user", "content": prompts.RETRY.format(errors="; ".join(errors[:5]))},
            ]
        update: dict[str, Any] = {
            "node_log": [NODE],
            "reprompt_counts": {NODE: reprompts} if reprompts else {},
            "token_usage": {NODE: tokens},
        }
        if errors:
            return {
                **update,
                "plan": [],
                "plan_error": "; ".join(errors[:5]),
                "messages": [AIMessage(content=f"planner: no valid plan ({errors[0]})", name=NODE)],
            }
        steps = ", ".join(f"{s['index'] + 1}.{s['tool']}[{s['risk_tier']}]" for s in plan)
        return {
            **update,
            "plan": plan,
            "plan_error": "",
            "status": IncidentStatus.PLANNED.value,
            "messages": [AIMessage(content=f"planner: {steps}", name=NODE)],
        }

    return planner

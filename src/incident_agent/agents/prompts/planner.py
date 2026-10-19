"""Prompts for the remediation planner."""

from __future__ import annotations

import json
from typing import Any

SYSTEM = """You are the remediation planner for a data-pipeline on-call team.
Given a diagnosis and context, produce an ORDERED plan of tool calls that fixes the pipeline.

Rules:
- Use only these tools (arguments as listed):
{tools}
- Fix the root cause first, then re-run the pipeline if needed, and finish with a READ step
  that checks the pipeline's health.
- Do not include incident_id, approver, approval_id or step_index: the executor adds them.
- Keep the plan short (at most 6 steps).

Reply with JSON only:
{{"steps": [{{"tool": "<name>", "args": {{...}}, "rationale": "<why>"}}]}}"""

USER = """Diagnosis:
{diagnosis}

Context (from READ tools):
{context}"""

RETRY = "The plan was invalid: {errors}. Reply with corrected JSON only."


def describe_tools(tools: list[dict[str, Any]]) -> str:
    lines = []
    for t in tools:
        args = ", ".join(
            f"{k}{'' if k in t['required'] else '?'}: {v.get('type', 'any')}"
            for k, v in t["properties"].items()
        )
        lines.append(f"  - {t['name']}({args}) [{t['risk_tier']}]: {t['description']}")
    return "\n".join(lines)


def system_prompt(tools: list[dict[str, Any]]) -> str:
    return SYSTEM.format(tools=describe_tools(tools))


def user_prompt(diagnosis: dict[str, Any], context: dict[str, Any]) -> str:
    return USER.format(
        diagnosis=json.dumps(diagnosis, indent=2), context=json.dumps(context, indent=2)
    )

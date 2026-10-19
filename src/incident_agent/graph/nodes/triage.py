"""Triage node (S19): classify an alert into an AlertType, or UNKNOWN (FR-01)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from incident_agent.agents.prompts import triage as prompts
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import IncidentState
from incident_agent.llm.base import ChatMessage, ModelError
from incident_agent.log import node_logger
from incident_agent.models import ALERT_REQUIRED_FIELDS, AlertType, IncidentStatus
from incident_agent.raw_loop.tokens import estimate_messages

NODE = "triage"


def alert_is_well_formed(alert: Any) -> bool:
    return isinstance(alert, dict) and all(
        isinstance(alert.get(k), str) and alert[k].strip() for k in ALERT_REQUIRED_FIELDS
    )


def parse_alert_type(content: str) -> AlertType | None:
    """Accept {"alert_type": X} (optionally wrapped in prose/code fences). None if unusable."""
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0)).get("alert_type", "")
    except (ValueError, AttributeError):
        return None
    value = str(value).strip().upper()
    return AlertType(value) if value in AlertType.__members__ else None


def make_triage_node(rt: Runtime) -> Callable[[IncidentState], dict[str, Any]]:
    def triage(state: IncidentState) -> dict[str, Any]:
        log = node_logger(__name__, state["incident_id"], NODE)
        alert = state.get("alert")
        reprompts = 0
        tokens = 0
        if not alert_is_well_formed(alert):
            alert_type = AlertType.UNKNOWN
            note = "triage: malformed alert -> UNKNOWN (model not consulted)"
        else:
            messages: list[ChatMessage] = [
                {"role": "system", "content": prompts.system_prompt()},
                {"role": "user", "content": prompts.user_prompt(alert)},
            ]
            alert_type = None
            for attempt in range(rt.settings.max_reprompts + 1):
                tokens = max(tokens, estimate_messages(messages))
                try:
                    reply = rt.model.chat(messages, purpose=NODE)
                except ModelError:
                    log.exception("model call failed")
                    raise
                alert_type = parse_alert_type(reply.get("content", ""))
                if alert_type is not None:
                    break
                reprompts = attempt + 1
                messages = [
                    *messages,
                    {"role": "assistant", "content": reply.get("content", "")},
                    {"role": "user", "content": prompts.RETRY},
                ]
            if alert_type is None:
                alert_type = AlertType.UNKNOWN
                reprompts = rt.settings.max_reprompts + 1
            note = f"triage: classified as {alert_type.value}"
        log.info(note)
        return {
            "alert_type": alert_type.value,
            "status": IncidentStatus.TRIAGED.value,
            "messages": [AIMessage(content=note, name=NODE)],
            "reprompt_counts": {NODE: reprompts} if reprompts else {},
            "token_usage": {NODE: tokens} if tokens else {},
            "node_log": [NODE],
        }

    return triage

"""Prompts for the triage node."""

from __future__ import annotations

import json

from incident_agent.models import Alert, AlertType

SYSTEM = """You classify data-pipeline alerts for an on-call team.
Allowed types: {types}.
Use UNKNOWN when the alert does not clearly match one type.
Reply with JSON only, exactly: {{"alert_type": "<TYPE>"}}"""

USER = """Alert:
{alert}"""

RETRY = 'That was not valid. Reply with JSON only, e.g. {"alert_type": "UNKNOWN"}.'


def system_prompt() -> str:
    return SYSTEM.format(types=", ".join(t.value for t in AlertType))


def user_prompt(alert: Alert) -> str:
    return USER.format(alert=json.dumps(alert, indent=2))

"""Scenario injector: emits the alert for a mocked failure, stamped with a fresh incident ID."""

from __future__ import annotations

import uuid

from incident_agent.mocks.fixtures import load_alert
from incident_agent.mocks.scenarios import get_scenario
from incident_agent.models import Alert


def new_incident_id(scenario_id: str) -> str:
    return f"INC-{scenario_id}-{uuid.uuid4().hex[:8]}"


def inject(scenario_id: str) -> tuple[str, Alert]:
    """Return (incident_id, alert). Raises UnknownScenarioError for an unknown ID."""
    get_scenario(scenario_id)
    alert: Alert = load_alert(scenario_id)  # type: ignore[assignment]
    return new_incident_id(scenario_id), alert

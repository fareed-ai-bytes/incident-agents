"""Supervisor routing (S20), fallback routing (S21). One test per routing-table row and branch."""

from __future__ import annotations

import pytest

from incident_agent.graph.routing import (
    FALLBACK,
    LOG_ANALYST,
    ROUTING_TABLE,
    SCHEMA_INSPECTOR,
    SUPERVISOR,
    WAREHOUSE_AGENT,
    WORKERS,
    route_after_triage,
    route_to_workers,
    supervisor,
)
from incident_agent.graph.state import initial_state
from incident_agent.models import AlertType


def _routed(alert_type):
    state = {**initial_state("INC-R", "x", {"pipeline": "p"}), "alert_type": alert_type}
    assert route_after_triage(state) == SUPERVISOR
    state = {**state, **{k: v for k, v in supervisor(state).items() if k != "messages"}}
    sends = route_to_workers(state)
    return [s.node for s in sends], sends


def test_routing_table_covers_every_known_type():
    assert set(ROUTING_TABLE) == set(AlertType) - {AlertType.UNKNOWN}


def test_route_schema_drift():
    targets, _ = _routed("SCHEMA_DRIFT")
    assert targets == [LOG_ANALYST, SCHEMA_INSPECTOR]


def test_route_auth_failure():
    targets, _ = _routed("AUTH_FAILURE")
    assert targets == [LOG_ANALYST]


def test_route_warehouse_unavailable():
    targets, _ = _routed("WAREHOUSE_UNAVAILABLE")
    assert targets == [WAREHOUSE_AGENT, LOG_ANALYST]


def test_route_late_data():
    targets, _ = _routed("LATE_DATA")
    assert targets == [WAREHOUSE_AGENT, LOG_ANALYST]


def test_route_transient_network():
    targets, _ = _routed("TRANSIENT_NETWORK")
    assert targets == [LOG_ANALYST]


@pytest.mark.parametrize("alert_type", [t.value for t in ROUTING_TABLE])
def test_workers_outside_the_row_are_never_sent(alert_type):
    targets, _ = _routed(alert_type)
    not_in_row = set(WORKERS) - set(ROUTING_TABLE[AlertType(alert_type)])
    assert not (set(targets) & not_in_row)


def test_send_payload_is_scoped_worker_input():
    _, sends = _routed("SCHEMA_DRIFT")
    assert set(sends[0].arg) == {"incident_id", "alert", "alert_type", "diagnosis_round"}
    assert sends[0].arg["diagnosis_round"] == 1


def test_unknown_alert_routes_to_fallback():
    state = {**initial_state("INC-R", "x", {}), "alert_type": "UNKNOWN"}
    assert route_after_triage(state) == FALLBACK
    assert route_after_triage({**state, "alert_type": "GARBAGE"}) == FALLBACK

"""SQLite checkpointer (S31)."""

from __future__ import annotations

import sqlite3

import pytest

from incident_agent.graph.runner import IncidentExistsError, IncidentNotFoundError, IncidentRunner
from incident_agent.llm.heuristic import HeuristicModel


@pytest.fixture
def runner(seeded, client):
    with IncidentRunner(seeded, model=HeuristicModel(), tools=client) as r:
        yield r


def test_every_transition_is_checkpointed_to_sqlite(runner, seeded):
    incident = runner.start("transient_network")
    assert runner.snapshot(incident).values["status"] == "RESOLVED"
    con = sqlite3.connect(seeded.checkpoint_db)
    count = con.execute(
        "SELECT count(*) FROM checkpoints WHERE thread_id = ?", (incident,)
    ).fetchone()[0]
    con.close()
    nodes_run = len(runner.snapshot(incident).values["node_log"])
    assert count >= nodes_run  # at least one checkpoint per node transition


def test_two_incidents_never_share_a_thread(runner):
    a = runner.start("transient_network")
    b = runner.start("transient_network")
    assert a != b
    assert set(runner.incident_ids()) >= {a, b}
    assert runner.snapshot(a).config["configurable"]["thread_id"] == a


def test_reusing_an_incident_id_is_refused(runner):
    from incident_agent.mocks.fixtures import load_alert

    incident = runner.start("transient_network")
    with pytest.raises(IncidentExistsError):
        runner.start_alert(incident, "transient_network", load_alert("transient_network"))


def test_unknown_incident(runner):
    with pytest.raises(IncidentNotFoundError):
        runner.snapshot("INC-nope")

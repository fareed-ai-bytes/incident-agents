"""Time-travel fork (S40)."""

from __future__ import annotations

import pytest

from incident_agent.graph.runner import ForkError, IncidentRunner
from incident_agent.llm.heuristic import HeuristicModel


@pytest.fixture
def runner(seeded, client):
    with IncidentRunner(seeded, model=HeuristicModel(), tools=client) as r:
        yield r


def _post_diagnosis(runner, incident):
    return next(c for c in runner.checkpoints(incident) if c.next == ("planner",))


def test_fork_from_checkpoint_changes_plan(runner):
    original = runner.start("schema_drift")
    before_ids = [c.checkpoint_id for c in runner.checkpoints(original)]
    before_plan = [s["tool"] for s in runner.snapshot(original).values["plan"]]
    assert before_plan[0] == "alter_table"

    cp = _post_diagnosis(runner, original)
    diag = runner.graph.get_state(
        {"configurable": {"thread_id": original, "checkpoint_id": cp.checkpoint_id}}
    ).values["diagnosis"]
    edited = {**diag, "category": "WAREHOUSE_UNAVAILABLE", "root_cause": "hypothesis: warehouse"}
    fork = runner.fork(original, cp.checkpoint_id, {"diagnosis": edited})

    assert fork == f"{original}-fork1"
    fork_values = runner.snapshot(fork).values
    fork_plan = [s["tool"] for s in fork_values["plan"]]
    assert "resume_warehouse" in fork_plan and "alter_table" not in fork_plan
    assert fork_values["diagnosis"]["category"] == "WAREHOUSE_UNAVAILABLE"
    # The fork skipped diagnosis: it resumed at the planner.
    assert fork_values["node_log"].count("planner") == 1
    assert fork_values["node_log"].count("triage") == 1  # copied history, not re-run

    # The original incident's history is untouched.
    assert [c.checkpoint_id for c in runner.checkpoints(original)] == before_ids
    assert [s["tool"] for s in runner.snapshot(original).values["plan"]] == before_plan


def test_fork_with_low_confidence_edit_routes_to_fallback(runner):
    original = runner.start("auth_failure")
    cp = _post_diagnosis(runner, original)
    diag = runner.snapshot(original).values["diagnosis"]
    fork = runner.fork(original, cp.checkpoint_id, {"diagnosis": {**diag, "confidence": 0.2}})
    assert runner.snapshot(fork).values["status"] == "ESCALATED"


def test_checkpoint_refs_and_bad_forks(runner):
    incident = runner.start("transient_network")
    infos = runner.checkpoints(incident)
    assert infos[0].step <= infos[-1].step
    assert runner.resolve_checkpoint(incident, "0") == infos[0].checkpoint_id
    with pytest.raises(ForkError, match="final"):
        runner.fork(incident, infos[-1].checkpoint_id, {})
    with pytest.raises(ForkError, match="next node"):
        runner.fork(incident, "0", {})  # before triage: not a supported fork point


def test_cli_checkpoints_and_fork(seeded, monkeypatch, capsys):
    from incident_agent.cli.main import main

    for key, value in seeded.as_env().items():
        monkeypatch.setenv(key, value)
    main(["run", "--scenario", "late_data", "--no-input"])
    incident = next(w for w in capsys.readouterr().out.split() if w.startswith("INC-late_data-"))
    assert main(["checkpoints", incident]) == 0
    listing = capsys.readouterr().out
    row = next(line for line in listing.splitlines() if " planner " in line)
    assert main(["fork", incident, row.split()[0], "--confidence", "0.1"]) == 0
    out = capsys.readouterr().out
    assert f"into {incident}-fork1" in out and "[ESCALATED]" in out

"""Human in the loop: interrupt + decisions (S37), diff rendering (S38)."""

from __future__ import annotations

import json

import pytest

from incident_agent.cli.main import approve_interactively
from incident_agent.cli.render import parse_choice
from incident_agent.graph.hitl import APPROVED, ApprovalSession, DecisionError
from incident_agent.graph.runner import IncidentRunner
from incident_agent.llm.heuristic import HeuristicModel
from incident_agent.mocks.job_runner import FakeJobRunner


@pytest.fixture
def runner(seeded, client):
    with IncidentRunner(seeded, model=HeuristicModel(), tools=client) as r:
        yield r


def _audit(settings, incident_id):
    return FakeJobRunner(settings.audit_db).audit_rows(incident_id)


class Script:
    """Stub approver: answers prompts from a list (no test ever waits on a human)."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []
        self.output = []

    def ask(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else ""

    def say(self, text):
        self.output.append(text)


# -- S37 --------------------------------------------------------------------------------------


def test_graph_halts_before_execute(runner, seeded):
    incident = runner.start("schema_drift")
    snap = runner.snapshot(incident)
    assert tuple(snap.next) == ("execute",)
    assert snap.values["status"] == "PENDING_APPROVAL"
    items = snap.values["pending_approval"]["items"]
    assert [(i["tool"], i["risk_tier"]) for i in items] == [
        ("alter_table", "DESTRUCTIVE"),
        ("rerun_job", "REVERSIBLE"),
    ]
    assert _audit(seeded, incident) == []  # nothing written while waiting
    assert runner.pending_incidents() == [incident]


def test_reject_routes_to_escalation_not_silent_end(runner, seeded):
    incident = runner.start("schema_drift")
    final = ApprovalSession(runner, incident, "ana").submit()  # undecided = rejected
    assert final["status"] == "ESCALATED"
    assert final["escalation"]["reason"] == "approval_rejected"
    assert "nothing was executed" in final["escalation"]["summary"]
    assert _audit(seeded, incident) == []


def test_approve_all_executes_and_resolves(runner, seeded):
    incident = runner.start("schema_drift")
    session = ApprovalSession(runner, incident, "ana")
    for idx in session.items:
        session.decide(idx, APPROVED)
    final = session.submit()
    assert final["status"] == "RESOLVED"
    rows = _audit(seeded, incident)
    assert [(r["action"], r["approver"]) for r in rows] == [
        ("alter_table", "ana"),
        ("rerun_job", "ana"),
    ]


def test_enter_alone_rejects():
    assert parse_choice("") == "reject"
    assert parse_choice("   ") == "reject"
    assert parse_choice(None) == "reject"
    assert parse_choice("yes") == "reject"  # only an explicit 'a' approves
    assert parse_choice("A") == "approve"
    assert parse_choice("edit") == "edit"


def test_interactive_enter_rejects_and_escalates(runner, seeded):
    incident = runner.start("auth_failure")
    script = Script(["", ""])
    final = approve_interactively(runner, incident, "ana", script.ask, script.say)
    assert final["status"] == "ESCALATED"
    assert all("(default: reject)" in p for p in script.prompts)
    assert _audit(seeded, incident) == []


def test_interactive_edit_validates_and_reshows_diff(runner, seeded):
    incident = runner.start("warehouse_unavailable")
    script = Script(
        [
            "e",
            '{"warehouse_name": 42}',  # wrong type -> rejected by schema validation
            "e",
            '{"warehouse_name": "TRANSFORM_WH"}',  # valid edit
            "a",  # approve resume_warehouse with edited args
            "a",  # approve rerun_job
        ]
    )
    approve_interactively(runner, incident, "ana", script.ask, script.say)
    text = "\n".join(script.output)
    assert "[FAILED] argument 'warehouse_name' should be string" in text
    assert "TRANSFORM_WH: state=RUNNING" in text  # diff re-rendered for the edited args
    rows = _audit(seeded, incident)
    assert rows[0]["action"] == "resume_warehouse"
    assert rows[0]["args"] == {"warehouse_name": "TRANSFORM_WH"}


def test_session_requires_pending_approval_and_approver(runner):
    incident = runner.start("transient_network")  # resolves without a gate
    with pytest.raises(DecisionError, match="no pending approval"):
        ApprovalSession(runner, incident, "ana")
    gated = runner.start("auth_failure")
    with pytest.raises(DecisionError, match="approver"):
        ApprovalSession(runner, gated, " ")


def test_cli_run_and_approvals_over_stdio(seeded, monkeypatch, capsys):
    from incident_agent.cli.main import main

    for key, value in seeded.as_env().items():
        monkeypatch.setenv(key, value)
    assert main(["run", "--scenario", "late_data", "--no-input"]) == 0
    out = capsys.readouterr().out
    for heading in ("Diagnosis", "Evidence", "Plan", "Pending action"):
        assert f"\n{heading}\n" in out
    assert "[PENDING]" in out and "backfill_partition [DESTRUCTIVE]" in out
    assert main(["approvals", "--no-input"]) == 0
    listing = capsys.readouterr().out
    assert "INC-late_data-" in listing and "0h 00m" in listing
    incident = next(w for w in listing.split() if w.startswith("INC-late_data-"))
    assert main(["show", incident]) == 0
    assert json.dumps("dt=2026-10-18")[1:-1] in capsys.readouterr().out


def test_cli_without_seed_fails_clearly(settings, monkeypatch, capsys):
    from incident_agent.cli.main import main

    for key, value in settings.as_env().items():
        monkeypatch.setenv(key, value)
    assert main(["approvals", "--no-input"]) == 1
    assert "run: python -m incident_agent.cli seed" in capsys.readouterr().err

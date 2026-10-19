import hashlib

import pytest

from incident_agent.errors import PermanentToolError, TransientToolError
from incident_agent.mocks import warehouse
from incident_agent.mocks.job_runner import FakeJobRunner


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_gated_write_without_approval_is_refused(settings):
    runner = FakeJobRunner(settings.audit_db)
    for tier in ("REVERSIBLE", "DESTRUCTIVE"):
        with pytest.raises(PermanentToolError, match="approval"):
            runner.record_write("INC-1", "rerun_job", {"pipeline": "p"}, tier, None, None)
    assert runner.audit_rows() == []


def test_write_records_audit_row_with_approver(settings):
    runner = FakeJobRunner(settings.audit_db)
    row = runner.record_write(
        "INC-1", "rerun_job", {"pipeline": "orders_warehouse_load"}, "REVERSIBLE", "ana", "AP-1", 0
    )
    assert row["approver"] == "ana" and row["status"] == "SUCCEEDED"
    assert [r["action"] for r in runner.audit_rows("INC-1")] == ["rerun_job"]


def test_replayed_write_executes_exactly_once(settings):
    runner = FakeJobRunner(settings.audit_db)
    args = {"pipeline": "orders_warehouse_load"}
    first = runner.record_write("INC-1", "rerun_job", args, "REVERSIBLE", "ana", "AP-1", 0)
    second = runner.record_write("INC-1", "rerun_job", args, "REVERSIBLE", "ana", "AP-1", 0)
    assert first["id"] == second["id"]
    assert len(runner.audit_rows("INC-1")) == 1


def test_write_touches_no_file_but_the_audit_db(settings):
    warehouse.seed(settings.warehouse_db)
    before = _digest(settings.warehouse_db)
    runner = FakeJobRunner(settings.audit_db)
    runner.record_write(
        "INC-1", "alter_table", {"table": "crm_customers"}, "DESTRUCTIVE", "ana", "AP-1", 0
    )
    assert _digest(settings.warehouse_db) == before
    assert not settings.checkpoint_db.exists()
    files = sorted(p.name for p in settings.audit_db.parent.iterdir())
    assert files == sorted([settings.audit_db.name, settings.warehouse_db.name])


def test_health_follows_recorded_fixes(settings):
    runner = FakeJobRunner(settings.audit_db)
    pipe = "orders_warehouse_load"
    assert runner.pipeline_health(pipe, "INC-1")["missing_fixes"] == [
        "rerun_job",
        "resume_warehouse",
    ]
    assert runner.job_status(pipe, "INC-1")["status"] == "FAILED"
    runner.record_write("INC-1", "resume_warehouse", {}, "REVERSIBLE", "ana", "AP-1", 0)
    runner.record_write("INC-1", "rerun_job", {}, "REVERSIBLE", "ana", "AP-1", 1)
    assert runner.pipeline_health(pipe, "INC-1")["healthy"] is True
    assert runner.job_status(pipe, "INC-1")["status"] == "SUCCEEDED"
    # Fixes are scoped to their incident.
    assert runner.pipeline_health(pipe, "INC-2")["healthy"] is False


def test_transient_scenario_fails_twice_then_succeeds(settings):
    runner = FakeJobRunner(settings.audit_db)
    for _ in range(2):
        with pytest.raises(TransientToolError):
            runner.job_status("inventory_glue_job", "INC-T")
    assert runner.job_status("inventory_glue_job", "INC-T")["status"] == "SUCCEEDED"

"""Fake job runner: records write actions to the SQLite audit DB and simulates job state.

Nothing here touches the warehouse or any other file: a "fix" exists only as an audit row,
and health checks are derived from which fixes were recorded for the incident.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from incident_agent.errors import PermanentToolError, TransientToolError
from incident_agent.mocks.scenarios import scenario_for_pipeline

GATED_TIERS = frozenset({"REVERSIBLE", "DESTRUCTIVE"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    action TEXT NOT NULL,
    args_json TEXT NOT NULL,
    risk_tier TEXT NOT NULL,
    approver TEXT,
    approval_id TEXT,
    step_index INTEGER,
    decision TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS audit_once
    ON audit_log (incident_id, approval_id, step_index, action);
CREATE TABLE IF NOT EXISTS tool_attempts (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL
);
"""


class AuditRow(TypedDict):
    id: int
    incident_id: str
    action: str
    args: dict[str, Any]
    risk_tier: str
    approver: str | None
    approval_id: str | None
    step_index: int | None
    decision: str
    status: str
    result: dict[str, Any]
    timestamp: str


class JobStatus(TypedDict):
    pipeline: str
    run_id: str
    status: str
    detail: str


class Health(TypedDict):
    pipeline: str
    healthy: bool
    applied_fixes: list[str]
    missing_fixes: list[str]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class FakeJobRunner:
    def __init__(self, audit_db: Path) -> None:
        self.audit_db = Path(audit_db)
        self.audit_db.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.audit_db, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    # -- writes ------------------------------------------------------------------------------

    def record_write(
        self,
        incident_id: str,
        action: str,
        args: dict[str, Any],
        risk_tier: str,
        approver: str | None,
        approval_id: str | None,
        step_index: int | None = None,
    ) -> AuditRow:
        """Record one write action. Gated tiers without an approval are refused (BR-01, FR-07).

        Idempotent per (incident, approval, step, action): replaying a step after a crash
        returns the original row instead of executing twice (verification.md S39).
        """
        if risk_tier in GATED_TIERS and not (approver and approval_id):
            raise PermanentToolError(
                f"{action} is {risk_tier} and needs an approval record (approver + approval_id)",
                action,
            )
        with self._conn() as con:
            existing = con.execute(
                "SELECT * FROM audit_log WHERE incident_id=? AND approval_id IS ? "
                "AND step_index IS ? AND action=? AND status='SUCCEEDED'",
                (incident_id, approval_id, step_index, action),
            ).fetchone()
            if existing:
                return _row(existing)
            result = {"ok": True, "message": f"{action} recorded by fake job runner"}
            cur = con.execute(
                "INSERT INTO audit_log (incident_id, action, args_json, risk_tier, approver, "
                "approval_id, step_index, decision, status, result_json, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    incident_id,
                    action,
                    json.dumps(args, sort_keys=True),
                    risk_tier,
                    approver,
                    approval_id,
                    step_index,
                    "approved" if risk_tier in GATED_TIERS else "auto",
                    "SUCCEEDED",
                    json.dumps(result),
                    utcnow(),
                ),
            )
            return _row(
                con.execute("SELECT * FROM audit_log WHERE id=?", (cur.lastrowid,)).fetchone()
            )

    # -- reads -------------------------------------------------------------------------------

    def bump_attempt(self, key: str) -> int:
        with self._conn() as con:
            con.execute(
                "INSERT INTO tool_attempts (key, count) VALUES (?, 1) "
                "ON CONFLICT(key) DO UPDATE SET count = count + 1",
                (key,),
            )
            return con.execute("SELECT count FROM tool_attempts WHERE key=?", (key,)).fetchone()[0]

    def simulate_transient(self, tool: str, pipeline: str, incident_id: str) -> None:
        """Raise TransientToolError for the scenario's first N calls of a read tool."""
        failures = scenario_for_pipeline(pipeline).transient_failures
        if failures <= 0:
            return
        n = self.bump_attempt(f"{tool}:{pipeline}:{incident_id}")
        if n <= failures:
            raise TransientToolError(
                f"connection reset by peer while calling {tool} (simulated, attempt {n})", tool
            )

    def applied_fixes(self, incident_id: str) -> list[str]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT DISTINCT action FROM audit_log WHERE incident_id=? AND status='SUCCEEDED'",
                (incident_id,),
            ).fetchall()
        return sorted(r[0] for r in rows)

    def job_status(self, pipeline: str, incident_id: str) -> JobStatus:
        scenario = scenario_for_pipeline(pipeline)
        self.simulate_transient("get_job_status", pipeline, incident_id)
        health = self.pipeline_health(pipeline, incident_id)
        if scenario.id == "transient_network":
            return {
                "pipeline": pipeline,
                "run_id": f"{pipeline}-0",
                "status": "SUCCEEDED",
                "detail": "scheduler automatic retry succeeded after a connection reset",
            }
        status = "SUCCEEDED" if health["healthy"] else "FAILED"
        detail = scenario.alert_message if status == "FAILED" else "rerun completed"
        return {"pipeline": pipeline, "run_id": f"{pipeline}-0", "status": status, "detail": detail}

    def pipeline_health(self, pipeline: str, incident_id: str) -> Health:
        scenario = scenario_for_pipeline(pipeline)
        applied = self.applied_fixes(incident_id)
        missing = sorted(scenario.required_fixes - set(applied))
        return {
            "pipeline": pipeline,
            "healthy": not missing,
            "applied_fixes": applied,
            "missing_fixes": missing,
        }

    def audit_rows(self, incident_id: str | None = None) -> list[AuditRow]:
        with self._conn() as con:
            if incident_id is None:
                rows = con.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM audit_log WHERE incident_id=? ORDER BY id", (incident_id,)
                ).fetchall()
        return [_row(r) for r in rows]


def _row(r: sqlite3.Row) -> AuditRow:
    return {
        "id": r["id"],
        "incident_id": r["incident_id"],
        "action": r["action"],
        "args": json.loads(r["args_json"]),
        "risk_tier": r["risk_tier"],
        "approver": r["approver"],
        "approval_id": r["approval_id"],
        "step_index": r["step_index"],
        "decision": r["decision"],
        "status": r["status"],
        "result": json.loads(r["result_json"]),
        "timestamp": r["timestamp"],
    }

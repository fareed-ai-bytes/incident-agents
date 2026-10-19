"""Durable approval requests (S39), stored in the SQLite audit DB.

The checkpointed graph state is the source of truth for an incident; this table makes pending
approvals listable across incidents (oldest first) and keeps the decision history for audit,
even after the process that requested them is gone.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict

from incident_agent.graph.state import PendingApproval
from incident_agent.models import ApprovalDecision

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL,
    risk_tier TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status TEXT NOT NULL,          -- PENDING | APPROVED | REJECTED | EXPIRED
    approver TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS approvals_pending ON approvals (status, requested_at);
"""


class ApprovalRow(TypedDict):
    approval_id: str
    incident_id: str
    step_index: int
    tool: str
    args: dict
    risk_tier: str
    requested_at: str
    status: str
    approver: str | None
    decided_at: str | None


class ApprovalStore:
    def __init__(self, audit_db: Path) -> None:
        self.path = Path(audit_db)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def add_pending(self, pending: PendingApproval) -> None:
        with self._conn() as con:
            con.executemany(
                "INSERT OR IGNORE INTO approvals (approval_id, incident_id, step_index, tool, "
                "args_json, risk_tier, requested_at, status) VALUES (?,?,?,?,?,?,?, 'PENDING')",
                [
                    (
                        i["approval_id"],
                        pending["incident_id"],
                        i["step_index"],
                        i["tool"],
                        json.dumps(i["args"], sort_keys=True),
                        i["risk_tier"],
                        pending["requested_at"],
                    )
                    for i in pending["items"]
                ],
            )

    def record(self, decisions: list[ApprovalDecision]) -> None:
        status = {"approved": "APPROVED", "rejected": "REJECTED", "expired": "EXPIRED"}
        with self._conn() as con:
            con.executemany(
                "UPDATE approvals SET status=?, approver=?, decided_at=?, args_json=? "
                "WHERE approval_id=? AND status='PENDING'",
                [
                    (
                        status[d["decision"]],
                        d["approver"],
                        d["decided_at"],
                        json.dumps(d["args"], sort_keys=True),
                        d["approval_id"],
                    )
                    for d in decisions
                ],
            )

    def rows(self, incident_id: str | None = None, status: str | None = None) -> list[ApprovalRow]:
        sql, params = "SELECT * FROM approvals WHERE 1=1", []
        if incident_id:
            sql, params = sql + " AND incident_id=?", [*params, incident_id]
        if status:
            sql, params = sql + " AND status=?", [*params, status]
        with self._conn() as con:
            found = con.execute(sql + " ORDER BY requested_at, approval_id", params).fetchall()
        return [
            {
                "approval_id": r["approval_id"],
                "incident_id": r["incident_id"],
                "step_index": r["step_index"],
                "tool": r["tool"],
                "args": json.loads(r["args_json"]),
                "risk_tier": r["risk_tier"],
                "requested_at": r["requested_at"],
                "status": r["status"],
                "approver": r["approver"],
                "decided_at": r["decided_at"],
            }
            for r in found
        ]

    def pending_incidents(self) -> list[tuple[str, str]]:
        """(requested_at, incident_id) for incidents with pending approvals, oldest first."""
        seen: dict[str, str] = {}
        for row in self.rows(status="PENDING"):
            seen.setdefault(row["incident_id"], row["requested_at"])
        return sorted((at, inc) for inc, at in seen.items())


def expired(requested_at: str, now: datetime, ttl_hours: float) -> bool:
    return now - datetime.fromisoformat(requested_at) > timedelta(hours=ttl_hours)

"""DuckDB stand-in for the Snowflake warehouse: business tables, load_audit, warehouse state.

Seeding is idempotent: every table is recreated and refilled, so running it twice leaves the
same row counts. Write tools never touch this file (they only record to the audit DB).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TypedDict

import duckdb

from incident_agent.mocks.scenarios import SCENARIOS

BUSINESS_TABLES = ("crm_customers", "payments", "orders", "events_daily", "inventory")


class ColumnInfo(TypedDict):
    name: str
    type: str


class LoadAuditRow(TypedDict):
    pipeline: str
    run_id: str
    started_at: str
    status: str
    rows_loaded: int
    error: str


class WarehouseStatus(TypedDict):
    warehouse: str
    state: str
    auto_resume: bool


_DDL = {
    "crm_customers": "id INTEGER, name VARCHAR, email VARCHAR, created_at TIMESTAMP",
    "payments": "id INTEGER, customer_id INTEGER, amount DECIMAL(10,2), paid_at TIMESTAMP",
    "orders": "id INTEGER, customer_id INTEGER, total DECIMAL(10,2), ordered_at TIMESTAMP",
    "events_daily": "event_id INTEGER, user_id INTEGER, event_type VARCHAR, dt DATE",
    "inventory": "sku VARCHAR, warehouse_code VARCHAR, qty INTEGER, updated_at TIMESTAMP",
}

RUN_DAY = date(2026, 10, 18)


class WarehouseError(RuntimeError):
    """A setup problem with the mock warehouse (fail fast, not an incident)."""


@contextmanager
def connect(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    if not Path(path).exists():
        raise WarehouseError(
            f"warehouse DB {path} not found; run `python -m incident_agent.mocks.seed`"
        )
    con = duckdb.connect(str(path))
    try:
        yield con
    finally:
        con.close()


def seed(path: Path) -> dict[str, int]:
    """(Re)create every table with deterministic rows. Returns row counts per table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        for table, ddl in _DDL.items():
            con.execute(f"CREATE OR REPLACE TABLE {table} ({ddl})")
        con.execute(
            "INSERT INTO crm_customers SELECT i, 'customer_' || i, 'c' || i || '@example.test', "
            "TIMESTAMP '2026-01-01' + to_days(i) FROM range(1, 201) t(i)"
        )
        con.execute(
            "INSERT INTO payments SELECT i, 1 + i % 200, round(10 + i * 1.37, 2), "
            "TIMESTAMP '2026-10-01' + to_hours(i) FROM range(1, 301) t(i)"
        )
        con.execute(
            "INSERT INTO orders SELECT i, 1 + i % 200, round(20 + i * 2.11, 2), "
            "TIMESTAMP '2026-10-01' + to_hours(i) FROM range(1, 401) t(i)"
        )
        # events_daily has every partition up to the day BEFORE the run day: the late one is missing.
        con.execute(
            "INSERT INTO events_daily SELECT i, 1 + i % 200, "
            "CASE i % 3 WHEN 0 THEN 'click' WHEN 1 THEN 'view' ELSE 'purchase' END, "
            f"DATE '{RUN_DAY - timedelta(days=7)}' + CAST(i % 7 AS INTEGER) FROM range(1, 701) t(i)"
        )
        con.execute(
            "INSERT INTO inventory SELECT 'SKU-' || i, 'WH' || (i % 4), i * 3, "
            "TIMESTAMP '2026-10-17' FROM range(1, 121) t(i)"
        )

        con.execute(
            "CREATE OR REPLACE TABLE load_audit (pipeline VARCHAR, run_id VARCHAR, "
            "started_at TIMESTAMP, status VARCHAR, rows_loaded INTEGER, error VARCHAR)"
        )
        for s in SCENARIOS.values():
            # Three healthy days, then today's failed run.
            for back in (3, 2, 1):
                con.execute(
                    "INSERT INTO load_audit VALUES (?, ?, ?, 'SUCCEEDED', ?, '')",
                    [
                        s.pipeline,
                        f"{s.pipeline}-{back}",
                        f"{RUN_DAY - timedelta(days=back)} 02:00:00",
                        1000 + back,
                    ],
                )
            con.execute(
                "INSERT INTO load_audit VALUES (?, ?, ?, 'FAILED', 0, ?)",
                [s.pipeline, f"{s.pipeline}-0", f"{RUN_DAY} 02:00:00", s.alert_message],
            )

        con.execute(
            "CREATE OR REPLACE TABLE warehouse_status (warehouse VARCHAR, state VARCHAR, auto_resume BOOLEAN)"
        )
        con.execute(
            "INSERT INTO warehouse_status VALUES ('LOAD_WH', 'SUSPENDED', false), "
            "('TRANSFORM_WH', 'RUNNING', true)"
        )
        con.execute(
            "CREATE OR REPLACE TABLE partitions (table_name VARCHAR, partition VARCHAR, arrived BOOLEAN)"
        )
        for back in range(7, 0, -1):
            con.execute(
                "INSERT INTO partitions VALUES ('events_daily', ?, true)",
                [f"dt={RUN_DAY - timedelta(days=back)}"],
            )
        con.execute("INSERT INTO partitions VALUES ('events_daily', ?, false)", [f"dt={RUN_DAY}"])
        return _row_counts(con)
    finally:
        con.close()


def _row_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    tables = [
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    ]
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in sorted(tables)}


def row_counts(path: Path) -> dict[str, int]:
    with connect(path) as con:
        return _row_counts(con)


def table_schema(path: Path, table: str) -> list[ColumnInfo]:
    with connect(path) as con:
        rows = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
    if not rows:
        raise LookupError(f"table {table!r} not found in warehouse")
    return [{"name": n, "type": t} for n, t in rows]


def load_audit(path: Path, pipeline: str, limit: int = 5) -> list[LoadAuditRow]:
    with connect(path) as con:
        rows = con.execute(
            "SELECT pipeline, run_id, CAST(started_at AS VARCHAR), status, rows_loaded, error "
            "FROM load_audit WHERE pipeline = ? ORDER BY started_at DESC LIMIT ?",
            [pipeline, limit],
        ).fetchall()
    keys = ("pipeline", "run_id", "started_at", "status", "rows_loaded", "error")
    return [dict(zip(keys, r, strict=True)) for r in rows]  # type: ignore[misc]


def warehouse_status(path: Path, warehouse: str) -> WarehouseStatus:
    with connect(path) as con:
        row = con.execute(
            "SELECT warehouse, state, auto_resume FROM warehouse_status WHERE warehouse = ?",
            [warehouse],
        ).fetchone()
    if row is None:
        raise LookupError(f"warehouse {warehouse!r} not found")
    return {"warehouse": row[0], "state": row[1], "auto_resume": bool(row[2])}


def partition_arrived(path: Path, table: str, partition: str) -> bool | None:
    """True/False if the partition is tracked, None if the table has no partition tracking."""
    with connect(path) as con:
        row = con.execute(
            "SELECT arrived FROM partitions WHERE table_name = ? AND partition = ?",
            [table, partition],
        ).fetchone()
    return None if row is None else bool(row[0])


def query_rows(path: Path, sql: str, params: list[Any] | None = None) -> list[tuple]:
    with connect(path) as con:
        return con.execute(sql, params or []).fetchall()

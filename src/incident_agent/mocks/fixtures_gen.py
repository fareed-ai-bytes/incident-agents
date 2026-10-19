"""Generate the committed log/alert/schema fixtures, deterministically.

Usage: python -m incident_agent.mocks.fixtures_gen [--out DIR]

Fixtures are generated, never hand-edited (rules.md). tests/unit/test_fixtures.py regenerates
them into a temp dir and asserts they match the committed files byte for byte.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from incident_agent.mocks.scenarios import FIXTURES_DIR, SCENARIOS, Scenario

START = datetime(2026, 10, 18, 2, 0, 0)

_NOISE = (
    ("INFO", "scheduler", "heartbeat ok for {pipeline}"),
    ("INFO", "extract", "fetched page {n} from source ({rows} rows)"),
    ("INFO", "transform", "applied {n} column mappings for {table}"),
    ("INFO", "loader", "staged batch {n} to @RAW_STAGE/{pipeline}/ ({rows} rows)"),
    ("DEBUG", "pool", "connection pool size=8 active={k}"),
    ("INFO", "monitor", "throughput {rows} rows/min"),
    ("INFO", "warehouse", "{warehouse} credit usage {n} units this hour"),
)

_RED_HERRINGS = (
    ("WARN", "monitor", "query queue latency 2.3s above 2.0s target"),
    ("ERROR", "metrics", "failed to push metrics to statsd:8125 (ignored, non-fatal)"),
    ("WARN", "extract", "source returned HTTP 429, backing off 1s (recovered)"),
)

# Lines just before the root cause, giving the ReAct loop something to narrow onto.
_LEAD_IN = {
    "schema_drift": [
        ("INFO", "schema", "source schema fingerprint changed: 5 columns -> 6 columns"),
        ("INFO", "loader", "starting COPY INTO RAW.CRM_CUSTOMERS from @RAW_STAGE"),
    ],
    "auth_failure": [
        ("INFO", "connector", "refreshing session for user SVC_FIVETRAN"),
        ("WARN", "connector", "login attempt 1 for SVC_FIVETRAN rejected"),
    ],
    "warehouse_unavailable": [
        ("INFO", "warehouse", "requesting LOAD_WH for COPY INTO RAW.ORDERS"),
        ("WARN", "warehouse", "LOAD_WH did not respond to resume request"),
    ],
    "late_data": [
        ("WARN", "sensor", "partition dt=2026-10-18 of events_raw not arrived (check 1/3)"),
        ("WARN", "sensor", "partition dt=2026-10-18 of events_raw not arrived (check 3/3)"),
    ],
    "transient_network": [
        ("INFO", "http", "GET https://inventory-api.mock.local/v2/stock?page=37"),
    ],
}

_FOLLOW_UP = {
    "transient_network": [
        ("INFO", "http", "retrying in 2s (attempt 2/3)"),
        ("INFO", "http", "GET https://inventory-api.mock.local/v2/stock?page=37 -> 200"),
    ],
}

_SOURCE_EXTRA_COLUMNS = {"schema_drift": [{"name": "loyalty_tier", "type": "VARCHAR"}]}

_WAREHOUSE_COLUMNS = {
    "crm_customers": [
        ("id", "INTEGER"),
        ("name", "VARCHAR"),
        ("email", "VARCHAR"),
        ("created_at", "TIMESTAMP"),
    ],
    "payments": [
        ("id", "INTEGER"),
        ("customer_id", "INTEGER"),
        ("amount", "DECIMAL(10,2)"),
        ("paid_at", "TIMESTAMP"),
    ],
    "orders": [
        ("id", "INTEGER"),
        ("customer_id", "INTEGER"),
        ("total", "DECIMAL(10,2)"),
        ("ordered_at", "TIMESTAMP"),
    ],
    "events_daily": [
        ("event_id", "INTEGER"),
        ("user_id", "INTEGER"),
        ("event_type", "VARCHAR"),
        ("dt", "DATE"),
    ],
    "inventory": [
        ("sku", "VARCHAR"),
        ("warehouse_code", "VARCHAR"),
        ("qty", "INTEGER"),
        ("updated_at", "TIMESTAMP"),
    ],
}


def _line(i: int, level: str, component: str, message: str) -> str:
    ts = (START + timedelta(milliseconds=500 * i)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    return f"{ts}Z {level:<5} [{component}] {message}"


def build_log(s: Scenario) -> list[str]:
    rng = random.Random(f"fixture-{s.id}")
    special: dict[int, tuple[str, str, str]] = {}
    lead = _LEAD_IN.get(s.id, [])
    for offset, entry in enumerate(lead):
        special[s.root_cause_line - len(lead) + offset] = entry
    level, rest = s.root_cause_text.split(" ", 1)
    component, message = rest.split("] ", 1)
    special[s.root_cause_line] = (level, component.strip("["), message)
    for offset, entry in enumerate(_FOLLOW_UP.get(s.id, []), start=1):
        special[s.root_cause_line + offset] = entry
    for herring in _RED_HERRINGS:
        pos = rng.randint(20, s.root_cause_line - 40)
        special.setdefault(pos, herring)
    final_status = "SUCCEEDED after automatic retry" if s.id == "transient_network" else "FAILED"
    special[s.log_lines - 1] = (
        "ERROR" if final_status == "FAILED" else "INFO",
        "scheduler",
        f"job {s.pipeline} run {s.pipeline}-0 finished with status {final_status}",
    )
    special[s.log_lines] = ("INFO", "scheduler", "alert dispatched to on-call rotation")

    lines = []
    for i in range(1, s.log_lines + 1):
        if i in special:
            lines.append(_line(i, *special[i]))
            continue
        lvl, comp, tmpl = _NOISE[rng.randrange(len(_NOISE))]
        msg = tmpl.format(
            pipeline=s.pipeline,
            table=s.table,
            warehouse=s.warehouse,
            n=rng.randint(1, 500),
            rows=rng.randint(100, 5000),
            k=rng.randint(0, 8),
        )
        lines.append(_line(i, lvl, comp, msg))
    return lines


def build_alert(s: Scenario) -> dict:
    return {
        "alert_id": f"ALERT-{s.id}",
        "source": "scheduler",
        "pipeline": s.pipeline,
        "severity": "high",
        "summary": s.alert_summary,
        "message": s.alert_message,
        "occurred_at": (START + timedelta(milliseconds=500 * s.log_lines)).isoformat() + "Z",
    }


def build_source_schema(s: Scenario) -> dict:
    cols = [{"name": n, "type": t} for n, t in _WAREHOUSE_COLUMNS[s.table]]
    return {"table": s.table, "columns": cols + _SOURCE_EXTRA_COLUMNS.get(s.id, [])}


def generate(out: Path = FIXTURES_DIR) -> list[Path]:
    written = []
    for s in SCENARIOS.values():
        d = out / s.id
        d.mkdir(parents=True, exist_ok=True)
        files = {
            "pipeline.log": "\n".join(build_log(s)) + "\n",
            "alert.json": json.dumps(build_alert(s), indent=2) + "\n",
            "source_schema.json": json.dumps(build_source_schema(s), indent=2) + "\n",
        }
        for name, content in files.items():
            path = d / name
            path.write_bytes(content.encode("utf-8"))
            written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=FIXTURES_DIR)
    args = parser.parse_args()
    generate(args.out)


if __name__ == "__main__":
    main()

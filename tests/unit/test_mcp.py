"""MCP server tools (S9-S11) and client discovery (S12)."""

from __future__ import annotations

import json

import anyio
import pytest
from mcp import Client

from incident_agent.mcp_server.server import build_server
from incident_agent.mocks import warehouse


@pytest.fixture
def server(settings):
    warehouse.seed(settings.warehouse_db)
    return build_server(settings)


def raw_call(server, name, args):
    """Call a tool through a real in-process MCP session; returns (is_error, payload)."""

    async def go():
        async with Client(server) as c:
            return await c.call_tool(name, args)

    res = anyio.run(go)
    text = res.content[0].text
    if res.is_error:
        return True, text
    return False, json.loads(text)


def raw_tools(server):
    async def go():
        async with Client(server) as c:
            return (await c.list_tools()).tools

    return {t.name: t for t in anyio.run(go)}


# -- S9: read tools ---------------------------------------------------------------------------


def test_read_fetch_log_window_pages(server):
    err, out = raw_call(
        server, "fetch_log_window", {"pipeline": "crm_customers_sync", "offset": 870, "limit": 10}
    )
    assert not err
    assert [ln["line"] for ln in out["lines"]] == list(range(870, 880))
    assert out["next_offset"] == 880 and out["total_lines"] == 1200


def test_read_fetch_log_window_refuses_limit_above_page_size(server, settings):
    err, msg = raw_call(
        server,
        "fetch_log_window",
        {"pipeline": "events_daily_partition", "offset": 1, "limit": settings.log_page_size + 1},
    )
    assert err and "[permanent]" in msg and "page size" in msg


def test_read_search_logs_finds_root_cause(server):
    err, out = raw_call(
        server, "search_logs", {"pipeline": "crm_customers_sync", "pattern": "loyalty_tier"}
    )
    assert not err and any(h["line"] == 874 for h in out["hits"])


def test_read_job_status_transient_errors_are_classified(server):
    args = {"pipeline": "inventory_glue_job", "incident_id": "INC-T"}
    err, msg = raw_call(server, "get_job_status", args)
    assert err and "[transient]" in msg
    raw_call(server, "get_job_status", args)
    err, out = raw_call(server, "get_job_status", args)
    assert not err and out["status"] == "SUCCEEDED"


def test_read_warehouse_status_and_partitions(server):
    err, out = raw_call(server, "get_warehouse_status", {"warehouse_name": "LOAD_WH"})
    assert out["state"] == "SUSPENDED"
    err, out = raw_call(
        server, "check_partition_arrival", {"table": "events_daily", "partition": "dt=2026-10-18"}
    )
    assert out["arrived"] is False


def test_read_unknown_pipeline_is_permanent_error(server):
    err, msg = raw_call(server, "get_pipeline_info", {"pipeline": "nope"})
    assert err and "[permanent]" in msg


# -- S10: metadata tools ----------------------------------------------------------------------


def test_schema_drift_detected_for_schema_drift_pipeline(server):
    err, out = raw_call(server, "compare_source_schema", {"pipeline": "crm_customers_sync"})
    assert not err and out["drift"] is True
    assert out["added"] == [{"name": "loyalty_tier", "type": "VARCHAR"}]


def test_schema_compare_identical_schemas_returns_no_differences(server):
    from incident_agent.mcp_server.metadata_tools import compare_schemas

    cols = [{"name": "id", "type": "INTEGER"}, {"name": "email", "type": "VARCHAR"}]
    assert compare_schemas(cols, list(cols)) == {"added": [], "removed": [], "type_changed": []}
    for pipeline in ("orders_warehouse_load", "payments_fivetran_sync", "events_daily_partition"):
        err, out = raw_call(server, "compare_source_schema", {"pipeline": pipeline})
        assert out["drift"] is False, pipeline


def test_schema_preview_alter_table_shows_before_and_after(server):
    args = {"table": "crm_customers", "add_columns": [{"name": "loyalty_tier", "type": "VARCHAR"}]}
    err, out = raw_call(server, "preview_write_action", {"tool": "alter_table", "args": args})
    assert not err
    assert not any("loyalty_tier" in line for line in out["before"])
    assert any("loyalty_tier" in line for line in out["after"])

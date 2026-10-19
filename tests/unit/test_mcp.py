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


# -- S11: write tools + risk tiers ------------------------------------------------------------


def test_write_every_tool_carries_a_risk_tier(server):
    tools = raw_tools(server)
    missing = [name for name, t in tools.items() if (t.meta or {}).get("risk_tier") is None]
    assert missing == []
    tiers = {name: t.meta["risk_tier"] for name, t in tools.items()}
    assert tiers["get_job_status"] == "READ"
    assert tiers["rerun_job"] == "REVERSIBLE"
    assert tiers["alter_table"] == tiers["backfill_partition"] == "DESTRUCTIVE"


def test_write_tools_refuse_without_approval(server, settings):
    from incident_agent.mocks.job_runner import FakeJobRunner

    err, msg = raw_call(
        server, "rerun_job", {"pipeline": "orders_warehouse_load", "incident_id": "INC-W"}
    )
    assert err and "[permanent]" in msg and "approval" in msg
    assert FakeJobRunner(settings.audit_db).audit_rows("INC-W") == []


def test_write_tool_with_approval_records_audit_row(server, settings):
    from incident_agent.mocks.job_runner import FakeJobRunner

    err, out = raw_call(
        server,
        "alter_table",
        {
            "table": "crm_customers",
            "add_columns": [{"name": "loyalty_tier", "type": "VARCHAR"}],
            "incident_id": "INC-W",
            "approver": "ana",
            "approval_id": "AP-1",
            "step_index": 0,
        },
    )
    assert not err and out["status"] == "SUCCEEDED"
    rows = FakeJobRunner(settings.audit_db).audit_rows("INC-W")
    assert [(r["action"], r["approver"], r["risk_tier"]) for r in rows] == [
        ("alter_table", "ana", "DESTRUCTIVE")
    ]


# -- S12: client discovery --------------------------------------------------------------------


@pytest.fixture
def client(server):
    from incident_agent.mcp_client import ToolClient

    with ToolClient(server) as c:
        yield c


def test_mcp_tool_discovery(client):
    specs = client.discover()
    assert {"fetch_log_window", "compare_source_schema", "alter_table"} <= set(specs)
    assert specs["alter_table"].risk_tier == "DESTRUCTIVE" and specs["alter_table"].is_write
    assert specs["search_logs"].risk_tier == "READ" and not specs["search_logs"].is_write
    assert "pattern" in specs["search_logs"].input_schema["properties"]


def test_client_call_and_error_classification(client):
    from incident_agent.errors import PermanentToolError, TransientToolError

    out = client.call("get_pipeline_info", {"pipeline": "crm_customers_sync"})
    assert out["table"] == "crm_customers"
    with pytest.raises(TransientToolError):
        client.call("get_job_status", {"pipeline": "inventory_glue_job", "incident_id": "INC-C"})
    with pytest.raises(PermanentToolError):
        client.call("get_pipeline_info", {"pipeline": "nope"})


def test_scoped_tools_enforce_allow_list(client):
    from incident_agent.errors import PermanentToolError

    scoped = client.scoped({"search_logs"})
    assert set(scoped.specs) == {"search_logs"}
    with pytest.raises(PermanentToolError, match="allow-list"):
        scoped.call("rerun_job", {"pipeline": "x", "incident_id": "y"})


def test_model_schema_hides_injected_args_and_validates(client):
    from incident_agent.mcp_client.schema import model_parameters, validate_args

    spec = client.spec("alter_table")
    params = model_parameters(spec)
    assert "approver" not in params["properties"] and "incident_id" not in params["required"]
    assert validate_args(spec, {"table": "t", "add_columns": []}) == []
    errors = validate_args(spec, {"table": 3, "bogus": 1})
    assert any("add_columns" in e for e in errors)
    assert any("bogus" in e for e in errors)
    assert any("'table'" in e for e in errors)


def test_mcp_client_does_not_import_server_package():
    from pathlib import Path

    import incident_agent.mcp_client as pkg

    for path in Path(pkg.__file__).parent.glob("*.py"):
        assert "mcp_server" not in path.read_text(encoding="utf-8"), path


def test_stdio_transport_discovers_tools(settings):
    """Spawn the real server process over stdio, as production does."""
    from incident_agent.mcp_client import ToolClient

    warehouse.seed(settings.warehouse_db)
    with ToolClient.from_settings(settings) as c:
        assert "fetch_log_window" in c.discover()
        out = c.call("search_logs", {"pipeline": "crm_customers_sync", "pattern": "loyalty_tier"})
        assert out["hits"]

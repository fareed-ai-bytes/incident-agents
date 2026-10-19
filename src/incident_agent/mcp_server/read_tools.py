"""READ tools: logs, job status, load audit, warehouse status, partitions, health (S9)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from incident_agent.errors import PermanentToolError
from incident_agent.mcp_server.common import ServerContext, register
from incident_agent.mocks import fixtures, warehouse
from incident_agent.mocks.scenarios import scenario_for_pipeline
from incident_agent.models import RiskTier

MAX_LINE_CHARS = 300


def _clip(text: str) -> str:
    return text if len(text) <= MAX_LINE_CHARS else text[: MAX_LINE_CHARS - 3] + "..."


def register_read_tools(server: MCPServer, ctx: ServerContext) -> None:
    page_size = ctx.settings.log_page_size

    def get_pipeline_info(pipeline: str) -> dict[str, Any]:
        s = scenario_for_pipeline(pipeline)
        return {
            "pipeline": s.pipeline,
            "warehouse": s.warehouse,
            "table": s.table,
            "partition": s.partition,
            "connector_user": "SVC_FIVETRAN",
            "log_lines": fixtures.log_length(pipeline),
        }

    def fetch_log_window(pipeline: str, offset: int, limit: int) -> dict[str, Any]:
        if limit > page_size:
            raise PermanentToolError(
                f"limit {limit} exceeds the page size of {page_size} lines; fetch in pages",
                "fetch_log_window",
            )
        if limit < 1 or offset < 1:
            raise PermanentToolError("offset and limit must be >= 1", "fetch_log_window")
        total = fixtures.log_length(pipeline)
        lines = fixtures.log_window(pipeline, offset, limit)
        nxt = offset + limit
        return {
            "pipeline": pipeline,
            "offset": offset,
            "total_lines": total,
            "next_offset": nxt if nxt <= total else None,
            "lines": [{"line": ln["line"], "text": _clip(ln["text"])} for ln in lines],
        }

    def search_logs(pipeline: str, pattern: str, max_hits: int = 20) -> dict[str, Any]:
        hits = fixtures.search_log(pipeline, pattern, min(max_hits, 50))
        return {
            "pipeline": pipeline,
            "pattern": pattern,
            "hits": [{"line": h["line"], "text": _clip(h["text"])} for h in hits],
        }

    def get_job_status(pipeline: str, incident_id: str) -> dict[str, Any]:
        return dict(ctx.runner.job_status(pipeline, incident_id))

    def get_load_audit(pipeline: str, limit: int = 5) -> dict[str, Any]:
        return {
            "pipeline": pipeline,
            "runs": warehouse.load_audit(ctx.settings.warehouse_db, pipeline, limit),
        }

    def get_warehouse_status(warehouse_name: str, incident_id: str = "") -> dict[str, Any]:
        status = dict(warehouse.warehouse_status(ctx.settings.warehouse_db, warehouse_name))
        if incident_id and "resume_warehouse" in ctx.runner.applied_fixes(incident_id):
            status["state"] = "RUNNING"
        return status

    def check_partition_arrival(
        table: str, partition: str, incident_id: str = ""
    ) -> dict[str, Any]:
        arrived = warehouse.partition_arrived(ctx.settings.warehouse_db, table, partition)
        if incident_id and "backfill_partition" in ctx.runner.applied_fixes(incident_id):
            arrived = True
        return {
            "table": table,
            "partition": partition,
            "tracked": arrived is not None,
            "arrived": arrived,
        }

    def check_pipeline_health(pipeline: str, incident_id: str) -> dict[str, Any]:
        return dict(ctx.runner.pipeline_health(pipeline, incident_id))

    tools = [
        (
            get_pipeline_info,
            "Static facts about a pipeline: warehouse, target table, partition, log size.",
        ),
        (fetch_log_window, f"Read up to {page_size} log lines starting at 1-based `offset`."),
        (search_logs, "Regex search over a pipeline log; returns matching line numbers and text."),
        (get_job_status, "Current status of the pipeline's latest run."),
        (
            get_load_audit,
            "Most recent load runs for a pipeline from the warehouse load_audit table.",
        ),
        (get_warehouse_status, "State (RUNNING/SUSPENDED) and auto_resume flag of a warehouse."),
        (check_partition_arrival, "Whether a table partition has arrived."),
        (check_pipeline_health, "Is the pipeline healthy again? Lists applied and missing fixes."),
    ]
    for fn, desc in tools:
        register(server, fn, RiskTier.READ, "read", desc)

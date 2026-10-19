"""Metadata tools (READ tier): schemas, drift comparison and write-action previews (S10)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from incident_agent.errors import PermanentToolError
from incident_agent.mcp_server.common import ServerContext, register
from incident_agent.mocks import fixtures, warehouse
from incident_agent.mocks.scenarios import scenario_for_pipeline
from incident_agent.models import RiskTier


def compare_schemas(
    source: list[dict[str, str]], target: list[dict[str, str]]
) -> dict[str, list[dict[str, str]]]:
    """Columns added in source, removed from source, or with a changed type."""
    src = {c["name"].lower(): c["type"].upper() for c in source}
    tgt = {c["name"].lower(): c["type"].upper() for c in target}
    return {
        "added": [{"name": n, "type": t} for n, t in src.items() if n not in tgt],
        "removed": [{"name": n, "type": t} for n, t in tgt.items() if n not in src],
        "type_changed": [
            {"name": n, "source_type": src[n], "target_type": tgt[n]}
            for n in src
            if n in tgt and src[n] != tgt[n]
        ],
    }


def _ddl(table: str, cols: list[dict[str, str]]) -> list[str]:
    body = [f"  {c['name']} {c['type']}," for c in cols]
    if body:
        body[-1] = body[-1].rstrip(",")
    return [f"CREATE TABLE {table} (", *body, ");"]


def register_metadata_tools(server: MCPServer, ctx: ServerContext) -> None:
    db = ctx.settings.warehouse_db

    def get_warehouse_schema(table: str) -> dict[str, Any]:
        return {"table": table, "columns": warehouse.table_schema(db, table)}

    def get_source_schema(pipeline: str) -> dict[str, Any]:
        return dict(fixtures.source_schema(pipeline))

    def compare_source_schema(pipeline: str) -> dict[str, Any]:
        source = fixtures.source_schema(pipeline)
        target = warehouse.table_schema(db, source["table"])
        diff = compare_schemas(source["columns"], list(target))
        drift = any(diff.values())
        return {"pipeline": pipeline, "table": source["table"], "drift": drift, **diff}

    def preview_write_action(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Before/after view of what a write tool would change, for the approval prompt."""
        if tool == "alter_table":
            table = args["table"]
            cols = list(warehouse.table_schema(db, table))
            added = [{"name": c["name"], "type": c["type"]} for c in args.get("add_columns", [])]
            before, after = _ddl(table, cols), _ddl(table, cols + added)
        elif tool == "backfill_partition":
            table, part = args["table"], args["partition"]
            arrived = warehouse.partition_arrived(db, table, part)
            before = [f"{table} {part}: arrived={arrived}, rows=0"]
            after = [
                f"{table} {part}: arrived=True, rows reloaded from s3://mock-bucket/events/",
                f"existing rows in {part} are DELETED then re-inserted",
            ]
        elif tool == "resume_warehouse":
            st = warehouse.warehouse_status(db, args["warehouse_name"])
            before = [f"{st['warehouse']}: state={st['state']} auto_resume={st['auto_resume']}"]
            after = [f"{st['warehouse']}: state=RUNNING auto_resume={st['auto_resume']}"]
        elif tool == "rerun_job":
            s = scenario_for_pipeline(args["pipeline"])
            before = [f"{s.pipeline}: last run {s.pipeline}-0 FAILED"]
            after = [f"{s.pipeline}: new run queued"]
        elif tool == "rotate_credentials":
            user = args.get("connector_user", "SVC_FIVETRAN")
            before = [f"{user}: password expired"]
            after = [f"{user}: password rotated; secret version incremented"]
        else:
            raise PermanentToolError(
                f"no preview available for tool {tool!r}", "preview_write_action"
            )
        return {"tool": tool, "before": before, "after": after}

    tools = [
        (get_warehouse_schema, "Columns and types of a warehouse table."),
        (get_source_schema, "Columns and types the source system currently sends for a pipeline."),
        (compare_source_schema, "Diff source vs warehouse schema: added, removed, type_changed."),
        (preview_write_action, "Before/after preview of a write action (no side effects)."),
    ]
    for fn, desc in tools:
        register(server, fn, RiskTier.READ, "metadata", desc)

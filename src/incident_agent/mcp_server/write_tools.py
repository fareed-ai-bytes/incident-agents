"""Write tools (S11). Each only records to the fake job runner's audit log.

`incident_id`, `approver`, `approval_id` and `step_index` are injected by the executor, never
chosen by a model. The job runner refuses gated tiers without an approval record.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from incident_agent.mcp_server.common import ServerContext, register
from incident_agent.models import RiskTier

# Declared tier of every write tool (BR-01). The planner can never downgrade these.
WRITE_TOOL_TIERS: dict[str, RiskTier] = {
    "rerun_job": RiskTier.REVERSIBLE,
    "resume_warehouse": RiskTier.REVERSIBLE,
    "rotate_credentials": RiskTier.REVERSIBLE,
    "alter_table": RiskTier.DESTRUCTIVE,
    "backfill_partition": RiskTier.DESTRUCTIVE,
}


def register_write_tools(server: MCPServer, ctx: ServerContext) -> None:
    def _record(
        action: str,
        args: dict[str, Any],
        incident_id: str,
        approver: str,
        approval_id: str,
        step_index: int,
    ) -> dict[str, Any]:
        row = ctx.runner.record_write(
            incident_id,
            action,
            args,
            WRITE_TOOL_TIERS[action].value,
            approver or None,
            approval_id or None,
            step_index,
        )
        return {"audit_id": row["id"], "action": action, "status": row["status"], **row["result"]}

    def rerun_job(
        pipeline: str,
        incident_id: str,
        approver: str = "",
        approval_id: str = "",
        step_index: int = 0,
    ) -> dict[str, Any]:
        return _record(
            "rerun_job", {"pipeline": pipeline}, incident_id, approver, approval_id, step_index
        )

    def resume_warehouse(
        warehouse_name: str,
        incident_id: str,
        approver: str = "",
        approval_id: str = "",
        step_index: int = 0,
    ) -> dict[str, Any]:
        return _record(
            "resume_warehouse",
            {"warehouse_name": warehouse_name},
            incident_id,
            approver,
            approval_id,
            step_index,
        )

    def rotate_credentials(
        connector_user: str,
        incident_id: str,
        approver: str = "",
        approval_id: str = "",
        step_index: int = 0,
    ) -> dict[str, Any]:
        return _record(
            "rotate_credentials",
            {"connector_user": connector_user},
            incident_id,
            approver,
            approval_id,
            step_index,
        )

    def alter_table(
        table: str,
        add_columns: list[dict[str, str]],
        incident_id: str,
        approver: str = "",
        approval_id: str = "",
        step_index: int = 0,
    ) -> dict[str, Any]:
        return _record(
            "alter_table",
            {"table": table, "add_columns": add_columns},
            incident_id,
            approver,
            approval_id,
            step_index,
        )

    def backfill_partition(
        table: str,
        partition: str,
        incident_id: str,
        approver: str = "",
        approval_id: str = "",
        step_index: int = 0,
    ) -> dict[str, Any]:
        return _record(
            "backfill_partition",
            {"table": table, "partition": partition},
            incident_id,
            approver,
            approval_id,
            step_index,
        )

    tools = [
        (rerun_job, "Queue a new run of the pipeline."),
        (resume_warehouse, "Resume a suspended warehouse."),
        (rotate_credentials, "Rotate the connector user's password and update the secret."),
        (alter_table, "ALTER TABLE ... ADD COLUMN for each column in add_columns."),
        (backfill_partition, "Delete and reload one partition of a table from the source bucket."),
    ]
    for fn, desc in tools:
        register(server, fn, WRITE_TOOL_TIERS[fn.__name__], "write", desc)

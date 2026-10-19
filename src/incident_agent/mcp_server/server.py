"""Build the local MCP server exposing every tool. Run with `python -m incident_agent.mcp_server`."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from incident_agent.config import Settings
from incident_agent.mcp_server.common import ServerContext
from incident_agent.mcp_server.metadata_tools import register_metadata_tools
from incident_agent.mcp_server.read_tools import register_read_tools
from incident_agent.mocks.job_runner import FakeJobRunner


def build_server(settings: Settings) -> MCPServer:
    server = MCPServer(
        "incident-agent-tools",
        instructions="Mock data-pipeline tools. Every tool declares meta.risk_tier.",
        log_level="WARNING",
    )
    ctx = ServerContext(settings=settings, runner=FakeJobRunner(settings.audit_db))
    register_read_tools(server, ctx)
    register_metadata_tools(server, ctx)
    return server

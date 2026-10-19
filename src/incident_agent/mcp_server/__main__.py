"""Entry point for the stdio MCP server process (spawned by the MCP client)."""

from incident_agent.config import Settings
from incident_agent.mcp_server.server import build_server

if __name__ == "__main__":
    build_server(Settings.from_env()).run("stdio")

"""Tool scoping per worker (S27): each worker sees only its allow-list; never a write tool."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from incident_agent.graph.nodes.workers import WORKER_TOOLS
from incident_agent.graph.routing import LOG_ANALYST, SCHEMA_INSPECTOR, WAREHOUSE_AGENT


def _scoped(client, worker):
    return client.scoped(WORKER_TOOLS[worker])


def _assert_read_only(scoped):
    writes = [name for name, spec in scoped.specs.items() if spec.is_write]
    assert writes == [], f"write tools exposed to a worker: {writes}"


def test_log_analyst_tools_are_scoped(client):
    scoped = _scoped(client, LOG_ANALYST)
    assert set(scoped.specs) == {"search_logs", "fetch_log_window", "get_pipeline_info"}
    _assert_read_only(scoped)


def test_schema_inspector_tools_are_scoped(client):
    scoped = _scoped(client, SCHEMA_INSPECTOR)
    assert "compare_source_schema" in scoped.specs
    assert "search_logs" not in scoped.specs
    _assert_read_only(scoped)


def test_warehouse_agent_tools_are_scoped(client):
    scoped = _scoped(client, WAREHOUSE_AGENT)
    assert {"get_warehouse_status", "check_partition_arrival"} <= set(scoped.specs)
    assert "compare_source_schema" not in scoped.specs
    _assert_read_only(scoped)


@pytest.mark.parametrize("worker", list(WORKER_TOOLS))
def test_no_write_tool_in_any_allow_list(worker, client):
    discovered = client.discover()
    writes = {n for n, s in discovered.items() if s.is_write}
    assert writes, "server should expose write tools"
    assert not (WORKER_TOOLS[worker] & writes)


@pytest.mark.parametrize("worker", list(WORKER_TOOLS))
def test_worker_cannot_call_outside_allow_list(worker, client):
    from incident_agent.errors import PermanentToolError

    with pytest.raises(PermanentToolError, match="allow-list"):
        _scoped(client, worker).call("rerun_job", {"pipeline": "p", "incident_id": "i"})


def test_agents_do_not_import_mock_backends():
    import incident_agent.agents as pkg

    pattern = re.compile(r"^\s*(from|import)\s+incident_agent\.mocks", re.MULTILINE)
    for path in Path(pkg.__file__).parent.rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path

"""Worker nodes (S24): each wraps one agent and returns a single finding as a state update.

The Log Analyst's raw ReAct loop runs unchanged inside its node; raw_loop/ knows nothing
about LangGraph. Workers receive a WorkerInput via Send, and only their allow-listed tools.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from incident_agent.agents import log_analyst, schema_inspector, warehouse_agent
from incident_agent.graph.routing import LOG_ANALYST, SCHEMA_INSPECTOR, WAREHOUSE_AGENT
from incident_agent.graph.runtime import Runtime
from incident_agent.graph.state import WorkerInput
from incident_agent.llm.base import ModelError
from incident_agent.log import node_logger
from incident_agent.models import AlertType, Finding

# Explicit allow-list per worker (rules.md). Write tools appear in none of them.
WORKER_TOOLS: dict[str, frozenset[str]] = {
    LOG_ANALYST: log_analyst.ALLOWED_TOOLS,
    SCHEMA_INSPECTOR: schema_inspector.ALLOWED_TOOLS,
    WAREHOUSE_AGENT: warehouse_agent.ALLOWED_TOOLS,
}

WorkerNode = Callable[[WorkerInput], dict[str, Any]]


def _update(worker: str, finding: Finding, retries: dict[str, int], **extra: Any) -> dict[str, Any]:
    note = f"{worker}: {finding['category']} ({finding['confidence']:.2f}) {finding['root_cause']}"
    return {
        "findings": [finding],
        "retry_counts": {f"{worker}.{k}": v for k, v in retries.items()},
        "messages": [AIMessage(content=note, name=worker)],
        "node_log": [worker],
        **extra,
    }


def _crashed(worker: str, exc: Exception, round_no: int) -> Finding:
    return {
        "worker": worker,
        "category": AlertType.UNKNOWN.value,
        "root_cause": f"{worker} failed: {exc}",
        "evidence": [],
        "confidence": 0.0,
        "status": "failed",
        "round": round_no,
    }


def make_worker_nodes(rt: Runtime) -> dict[str, WorkerNode]:
    def log_analyst_node(inp: WorkerInput) -> dict[str, Any]:
        log = node_logger(__name__, inp["incident_id"], LOG_ANALYST)
        tools = rt.tools.scoped(WORKER_TOOLS[LOG_ANALYST])
        try:
            analysis = log_analyst.run_log_analyst(
                rt.model,
                tools,
                inp["alert"],
                inp["alert_type"],
                inp["incident_id"],
                rt.settings,
                inp["diagnosis_round"],
            )
        except ModelError as exc:
            log.exception("log analyst model failure")
            return _update(LOG_ANALYST, _crashed(LOG_ANALYST, exc, inp["diagnosis_round"]), {})
        loop = analysis.loop
        log.info(
            "loop %s after %d iterations, %d re-prompts, max prompt ~%d tokens",
            loop.status,
            loop.iterations,
            loop.reprompts,
            loop.max_prompt_tokens,
        )
        return _update(
            LOG_ANALYST,
            analysis.finding,
            analysis.retries,
            reprompt_counts={LOG_ANALYST: loop.reprompts} if loop.reprompts else {},
            token_usage={LOG_ANALYST: loop.max_prompt_tokens},
            summary_note=loop.summary_note,
        )

    def schema_inspector_node(inp: WorkerInput) -> dict[str, Any]:
        finding, retries = schema_inspector.run_schema_inspector(
            rt.tools.scoped(WORKER_TOOLS[SCHEMA_INSPECTOR]),
            inp["alert"],
            inp["incident_id"],
            rt.retry_policy,
            inp["diagnosis_round"],
        )
        return _update(SCHEMA_INSPECTOR, finding, retries)

    def warehouse_agent_node(inp: WorkerInput) -> dict[str, Any]:
        finding, retries = warehouse_agent.run_warehouse_agent(
            rt.tools.scoped(WORKER_TOOLS[WAREHOUSE_AGENT]),
            inp["alert"],
            inp["incident_id"],
            rt.retry_policy,
            inp["diagnosis_round"],
        )
        return _update(WAREHOUSE_AGENT, finding, retries)

    return {
        LOG_ANALYST: log_analyst_node,
        SCHEMA_INSPECTOR: schema_inspector_node,
        WAREHOUSE_AGENT: warehouse_agent_node,
    }

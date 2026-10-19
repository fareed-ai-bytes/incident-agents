"""Log Analyst: finds the root cause in paginated logs with the raw ReAct loop (S17)."""

from __future__ import annotations

from dataclasses import dataclass, field

from incident_agent.agents.common import RetryingTools, clamp_confidence
from incident_agent.agents.prompts import log_analyst as prompts
from incident_agent.config import Settings
from incident_agent.llm.base import ChatModel
from incident_agent.mcp_client import ScopedTools
from incident_agent.models import Alert, AlertType, Finding
from incident_agent.raw_loop import LoopResult, run_react_loop
from incident_agent.raw_loop.memory import Transcript
from incident_agent.raw_loop.retry import RetryPolicy

WORKER = "log_analyst"
ALLOWED_TOOLS = frozenset({"search_logs", "fetch_log_window", "get_pipeline_info"})


@dataclass
class LogAnalysis:
    finding: Finding
    loop: LoopResult
    retries: dict[str, int] = field(default_factory=dict)


def make_transcript(settings: Settings) -> Transcript:
    return Transcript()


def run_log_analyst(
    model: ChatModel,
    tools: ScopedTools,
    alert: Alert,
    alert_type: str,
    incident_id: str,
    settings: Settings,
    round_no: int = 1,
) -> LogAnalysis:
    retrying = RetryingTools(
        tools,
        RetryPolicy(settings.max_tool_attempts, settings.retry_base_delay),
        incident_id,
    )
    task = prompts.TASK.format(
        incident_id=incident_id,
        pipeline=alert["pipeline"],
        alert_type=alert_type,
        summary=alert.get("summary", ""),
        message=alert.get("message", ""),
    )
    result = run_react_loop(
        model,
        retrying.loop_tools(),
        system=prompts.system_prompt(settings.log_page_size),
        task=task,
        final_parameters=prompts.FINAL_PARAMETERS,
        max_iterations=settings.max_iterations,
        max_reprompts=settings.max_reprompts,
        transcript=make_transcript(settings),
        purpose=WORKER,
    )
    return LogAnalysis(_to_finding(result, round_no), result, dict(retrying.retries))


def _to_finding(result: LoopResult, round_no: int) -> Finding:
    if result.status == "complete" and result.answer is not None:
        ans = result.answer
        category = str(ans.get("category", "")).upper()
        if category not in AlertType.__members__:
            category = AlertType.UNKNOWN.value
        evidence = ans.get("evidence") or []
        return {
            "worker": WORKER,
            "category": category,
            "root_cause": str(ans.get("root_cause", "")),
            "evidence": [str(e) for e in evidence][:10],
            "confidence": clamp_confidence(ans.get("confidence")),
            "status": "complete",
            "round": round_no,
        }
    # BR-02: an incomplete or failed loop yields a partial finding with confidence 0.
    evidence = [f"L? {s.tool}({s.args}) -> {s.observation[:160]}" for s in result.steps[-3:]]
    if result.summary_note:
        evidence.insert(0, f"summary: {result.summary_note[:300]}")
    reason = (
        f"log analysis incomplete after {result.iterations} iterations"
        if result.status == "incomplete"
        else f"log analysis failed: {result.error}"
    )
    return {
        "worker": WORKER,
        "category": AlertType.UNKNOWN.value,
        "root_cause": reason,
        "evidence": evidence,
        "confidence": 0.0,
        "status": result.status,
        "round": round_no,
    }

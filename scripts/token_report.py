"""Per-node prompt tokens and triage-to-plan time for each scenario (S35, S42).

Usage: python scripts/token_report.py [--model heuristic|ollama] [--runs 3]

Runs every scenario up to the approval gate (no approvals are given; nothing is written),
then prints the max prompt tokens per node against its budget, and timing. Uses temporary
databases, so ./var is untouched.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from incident_agent.config import Settings
from incident_agent.graph.runner import IncidentRunner
from incident_agent.mcp_client import ToolClient
from incident_agent.mocks.scenarios import SCENARIOS
from incident_agent.mocks.seed import seed_all
from incident_agent.policy.budgets import NODE_BUDGETS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["heuristic", "ollama"], default="heuristic")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="incident-agent-report-"))
    settings = replace(Settings.from_env(), model_provider=args.model).with_paths(tmp)
    seed_all(settings)
    tools = ToolClient.from_settings(settings)  # real stdio MCP server process
    peak: dict[str, int] = {}
    timings: dict[str, list[float]] = {s: [] for s in SCENARIOS}
    outcomes: dict[str, str] = {}
    with IncidentRunner(settings, tools=tools) as runner:
        for _ in range(args.runs):
            for scenario in SCENARIOS:
                start = time.perf_counter()
                incident = runner.start(scenario)
                timings[scenario].append(time.perf_counter() - start)
                values = runner.snapshot(incident).values
                diag = values.get("diagnosis") or {}
                outcomes[scenario] = (
                    f"{diag.get('category')} {diag.get('confidence', 0):.2f} -> {values['status']}"
                )
                for node, tokens in values.get("token_usage", {}).items():
                    peak[node] = max(peak.get(node, 0), tokens)
    tools.close()

    print(f"model={args.model} runs={args.runs}")
    print("\n| Node | Max prompt tokens | Budget | Within budget |")
    print("|---|---|---|---|")
    for node, budget in NODE_BUDGETS.items():
        used = peak.get(node, 0)
        print(f"| {node} | {used} | {budget} | {'yes' if used <= budget else 'NO'} |")
    print("\n| Scenario | Outcome (last run) | Median triage-to-plan s | Max s |")
    print("|---|---|---|---|")
    for scenario, ts in timings.items():
        print(
            f"| {scenario} | {outcomes[scenario]} | {statistics.median(ts):.2f} | {max(ts):.2f} |"
        )
    over = [n for n, b in NODE_BUDGETS.items() if peak.get(n, 0) > b]
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())

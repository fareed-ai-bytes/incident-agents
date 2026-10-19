"""S3 benchmark: how reliably does each local model emit a correct tool call?

Usage: python scripts/bench_tools.py --runs 20 --models qwen2.5:7b-instruct llama3.1:8b

Every model gets the same prompts and temperature. A run passes only if the model calls the
expected tool with JSON arguments that parse and carry the required keys. Paste the printed
table into docs/memory.md (decisions log) together with the go/no-go call.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass

from incident_agent.config import Settings
from incident_agent.llm.base import ModelError, tool_schema
from incident_agent.llm.ollama import OllamaChatModel

GO_THRESHOLD = 0.8  # go/no-go: at least 80% valid tool calls

TOOLS = [
    tool_schema(
        "search_logs",
        "Search a pipeline's log for lines matching a regex. Returns line numbers and text.",
        {
            "type": "object",
            "properties": {
                "pipeline": {"type": "string"},
                "pattern": {"type": "string"},
            },
            "required": ["pipeline", "pattern"],
        },
    ),
    tool_schema(
        "fetch_log_window",
        "Fetch up to 200 log lines starting at offset.",
        {
            "type": "object",
            "properties": {
                "pipeline": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["pipeline", "offset", "limit"],
        },
    ),
]

CASES = [
    (
        "The load for pipeline crm_customers_sync failed. Find the error lines in its log.",
        "search_logs",
    ),
    (
        "search_logs found an ERROR at line 1840 of pipeline events_daily_partition. "
        "Read the 50 lines before and after it.",
        "fetch_log_window",
    ),
]


@dataclass
class Result:
    model: str
    runs: int
    passed: int
    malformed: int
    wrong_tool: int
    seconds: float

    @property
    def rate(self) -> float:
        return self.passed / self.runs if self.runs else 0.0


def check(msg: dict, expected: str) -> str:
    calls = msg.get("tool_calls") or []
    if not calls:
        return "malformed"
    fn = calls[0]["function"]
    if fn["name"] != expected:
        return "wrong_tool"
    try:
        args = json.loads(fn["arguments"])
    except (TypeError, ValueError):
        return "malformed"
    required = next(t for t in TOOLS if t["function"]["name"] == expected)["function"][
        "parameters"
    ]["required"]
    return "pass" if isinstance(args, dict) and all(k in args for k in required) else "malformed"


def bench(model_name: str, runs: int, base_url: str) -> Result:
    model = OllamaChatModel(model_name, base_url, temperature=0.0)
    res = Result(model_name, 0, 0, 0, 0, 0.0)
    start = time.perf_counter()
    for i in range(runs):
        prompt, expected = CASES[i % len(CASES)]
        msg = model.chat(
            [
                {"role": "system", "content": "You are a data-pipeline on-call assistant."},
                {"role": "user", "content": prompt},
            ],
            TOOLS,
            purpose="bench",
        )
        outcome = check(msg, expected)
        res.runs += 1
        res.passed += outcome == "pass"
        res.malformed += outcome == "malformed"
        res.wrong_tool += outcome == "wrong_tool"
    res.seconds = time.perf_counter() - start
    return res


def main() -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--models", nargs="+", default=[settings.model_name])
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2; a pass rate is never counted from one run")

    results = []
    for name in args.models:
        try:
            results.append(bench(name, args.runs, settings.ollama_base_url))
        except ModelError as exc:
            print(f"[FAILED] {name}: {exc}")
            return 1

    print("| Model | Runs | Pass | Malformed | Wrong tool | Pass rate | Avg s/run |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r.model} | {r.runs} | {r.passed} | {r.malformed} | {r.wrong_tool} "
            f"| {r.rate:.0%} | {r.seconds / max(r.runs, 1):.1f} |"
        )
    best = max(results, key=lambda r: (r.rate, -r.seconds))
    verdict = "GO" if best.rate >= GO_THRESHOLD else "NO-GO"
    print(f"\n{verdict}: best model {best.model} at {best.rate:.0%} (threshold {GO_THRESHOLD:.0%})")
    return 0 if verdict == "GO" else 2


if __name__ == "__main__":
    sys.exit(main())

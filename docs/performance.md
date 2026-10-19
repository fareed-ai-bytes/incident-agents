# Performance — Pipeline Incident Response Agent
_Last measured: 2026-10-19 · Every number below lists the command that produced it (verification.md S42)._

> All figures so far come from the **offline heuristic model** (`MODEL_PROVIDER=heuristic`) on the
> dev laptop. They measure the plumbing — graph, MCP stdio round-trips, retries, SQLite
> checkpoints — not a real LLM. Re-run with `--model ollama` once S3 picks a model and add a
> second column; do not compare the two as if they were the same thing.

## Token budget
Command: `python scripts/token_report.py --model heuristic --runs 3`

Budgets live in `src/incident_agent/policy/budgets.py`, sized for an 8k-context model (BR-07).
Tokens are estimated as characters / 4.

| Node | Max prompt tokens (heuristic) | Budget | Within budget |
|---|---|---|---|
| triage | 159 | 1500 | yes |
| log_analyst | 1185 | 6000 | yes |
| planner | 849 | 4000 | yes |

The `late_data` log is ~6000 lines (~120k tokens). It is never sent whole: the Log Analyst reads it
with `search_logs` and `fetch_log_window` pages of at most 200 lines (`LOG_PAGE_SIZE`), observations
are capped at 4000 characters, and the sliding window keeps 3 observations verbatim
(`tests/unit/test_pagination.py::test_oversized_log_is_read_in_pages_within_budget`).

## Triage-to-plan time
Same command. Time from alert to the approval gate (or to RESOLVED for transient_network), over
the real stdio MCP server, excluding any human wait.

| Scenario | Outcome | Median s | Max s |
|---|---|---|---|
| schema_drift | SCHEMA_DRIFT 0.88 -> PENDING_APPROVAL | 0.17 | 0.25 |
| auth_failure | AUTH_FAILURE 0.85 -> PENDING_APPROVAL | 0.07 | 0.07 |
| warehouse_unavailable | WAREHOUSE_UNAVAILABLE 0.88 -> PENDING_APPROVAL | 0.10 | 0.12 |
| late_data | LATE_DATA 0.85 -> PENDING_APPROVAL | 0.13 | 0.15 |
| transient_network | TRANSIENT_NETWORK 0.85 -> RESOLVED | 0.92 | 0.94 |

transient_network is slower because the scheduler's job-status tool fails twice with a simulated
connection reset; the retries back off 0.2 s then 0.4 s (+ jitter) before succeeding (BR-04).

Reproduction check: an earlier run of the same command gave 0.12 / 0.06 / 0.09 / 0.12 / 1.08 s
medians and identical token peaks (159 / 1185 / 849). Token peaks are deterministic; sub-second
timings vary with machine load.

## Test-suite runtime
Command: `pytest -q` — 225 passed, 5 skipped in 79-95 s across four consecutive runs (2026-10-19).
Most of that is MCP sessions and the stdio server subprocess spawned by several tests.

## Retries and re-prompts
Visible per incident with `python -m incident_agent.cli show <incident> --verbose` (Counters
section: `retry_counts`, `reprompt_counts`, `token_usage`).

| What | Heuristic run | Real model |
|---|---|---|
| Tool-level retries (transient_network) | 2 per `get_job_status` call | TODO |
| Model re-prompts (BR-05) | 0 (the heuristic model never emits malformed calls) | TODO — expected to be non-zero (memory.md) |

## To do with a real model (after S3)
- `python scripts/bench_tools.py --runs 20 --models <a> <b>` → pass rates into memory.md.
- `python scripts/token_report.py --model ollama --runs 3` → add a "real model" column above.
- Median triage-to-plan time vs the "minutes, not hours" claim (product.md success metrics).

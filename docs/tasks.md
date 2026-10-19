# Tasks & Progress — Pipeline Incident Response Agent
_Claude: update this at the end of every session. Keep DONE to the last ~10 items; archive older ones._
_Task IDs match the Jira import (incident_agent_jira_import.csv). Full acceptance criteria live in Jira; the summaries here are for session pickup._

## Current focus
All 44 stories are implemented, with automated checks passing (225 passed, 5 real-model tests
skipped). What is left is the MANUAL / real-model evidence: it needs Ollama, which is not
installed on the dev laptop yet. Start there: S2 → S3 decides the model.

## IN PROGRESS
- [ ] S3 Benchmark tool-calling of 2+ local models — code done (`scripts/bench_tools.py`); next: install Ollama, run `--runs 20` on two models, record pass rates + GO/NO-GO in memory.md

## TODO (prioritised, top = next) — manual evidence still owed
- [ ] S2 Ollama smoke test, MANUAL: `python scripts/smoke_model.py` with Ollama running (the "stopped" case was verified: fails in ~5 s with a clear message)
- [ ] S17 Real-model Log Analyst: schema_drift 5 runs, root cause correct >= 4/5
- [ ] S19 Real-model triage of the 5 alerts
- [ ] S28 Real-model plan for schema_drift, reviewed
- [ ] S32 Manual Ctrl+C mid-diagnosis, then `cli resume <incident>` (automated equivalent passes)
- [ ] S35 `scripts/token_report.py --model ollama` (heuristic run within budget, see performance.md)
- [ ] S37 Manual approve / reject / edit once each in a real terminal (automated equivalents pass)
- [ ] S38 View a DESTRUCTIVE prompt with `NO_COLOR=1` in a terminal (automated check passes)
- [ ] S39 Manual kill-at-approval → restart → `cli approvals` → approve; audit log shows one row (automated e2e passes)
- [ ] S40 Manual `cli checkpoints` + `cli fork` (CLI test passes; output captured once in this session)
- [ ] S41 `RUN_REAL_MODEL=1 pytest tests/e2e -q` with the chosen model
- [ ] S42 Add real-model columns to performance.md
- [ ] S44 Fresh-machine README dry run by a second person

## BLOCKED
- [ ] Every real-model check above — blocked by: Ollama not installed on this machine; S3 model decision

## DONE (recent) — 2026-10-19, one commit (or more) per story on `main`
- [x] S36–S40 Risk policy tests, interrupt + CLI approvals (Enter rejects), destructive diff gate, durable approvals, time-travel fork
- [x] S31–S35 SQLite checkpointer, resume after restart, token budgets, sliding window, paginated logs
- [x] S28–S30 Planner (tiers can't be downgraded), executor (stops on first failure), verify loop (BR-06)
- [x] S18–S27 State + reducers, triage, routing table, fallback, Schema Inspector, Warehouse Agent, workers as nodes, parallel fan-out, aggregation, tool scoping
- [x] S13–S17 Raw ReAct loop, max_iterations, re-prompts, tool retry, Log Analyst
- [x] S5–S12 DuckDB mock, generated fixtures, fake job runner, injector CLI, MCP server (read/metadata/write) + client discovery
- [x] S1–S4 Repo skeleton (pinned deps, ruff, pytest), Ollama client + smoke script, bench script, context docs filled
- [x] S41–S44 E2E for 5 scenarios, performance.md, TOPICS.md proofs, README

## Known bugs / tech debt
- Commit d3b1a1c [S30] accidentally also contains the S31/S32 runner + test files (written while that commit's tests were running); 3ad4365 [S31][S32] completes them. History was not rewritten.
- One full-suite pass during S40 ran far slower than usual (the tool timeout hit at 600 s); three immediate re-runs with `faulthandler_timeout` took 79–95 s and showed no stall. Watch for it: if it recurs, the faulthandler dump in the pytest log shows where.
- Confidence threshold (BR-03 0.6), log page size (BR-07 200), node budgets and approval expiry (BR-08 24 h) are still placeholders until S3.
- Product open question still open: should a rejected approval go back to the planner for an alternative? Today it escalates (BR-09).

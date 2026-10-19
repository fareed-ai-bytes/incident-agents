# Project Memory — Pipeline Incident Response Agent
<!-- Append-only log of things a new engineer (or a fresh Claude session) would get wrong.
     NOT a task list (tasks.md) and NOT a restatement of architecture (architecture.md).
     Prune when it passes ~150 lines. -->

## Decisions log
| Date | Decision | Why | Alternatives rejected |
|---|---|---|---|
| 2026-10-19 | Use case: data-pipeline incident response | Real L2/L3 managed-services work; write actions make approval gates meaningful; covers all 16 syllabus topics without forcing any | IT service-desk triage — overdone, approvals low-stakes. Access review/JML — strong HITL but weak ReAct fit. DR drill — weak sliding-window fit. Vuln remediation — high mock effort |
| 2026-10-19 | Local open models via Ollama only | Client logs, schemas and connection metadata cannot leave the environment | Hosted APIs — would make the "local" requirement arbitrary |
| 2026-10-19 | All backends mocked (DuckDB, JSON fixtures, fake job runner) | Reproducible for reviewers; a hallucinated write cannot touch real systems | Real AWS/Snowflake sandbox — unreproducible, risky, slow to set up |
| 2026-10-19 | Log Analyst built as a raw SDK ReAct loop, wrapped as a graph node | Covers Day 16 mechanics while still living inside the Day 17 graph | Building every worker with LangGraph prebuilt agents — hides the loop mechanics |
| 2026-10-19 | Two separate retry mechanisms: tool-level backoff and model-level re-prompt | They fail for different reasons and need different caps | One generic retry wrapper — would retry permanent errors and hide model formatting issues |
| 2026-10-19 | Backlog stories capped at 2 points; delivered as a Jira CSV | Small, verifiable increments; direct import | Word doc backlog — would need retyping |
| 2026-10-19 | Pinned LangGraph 1.2.16, MCP SDK 2.3.0, DuckDB 1.5.6, langgraph-checkpoint-sqlite 3.1.2 | Current releases at build time; MCP 2.x renames FastMCP to `MCPServer` and its `Client` can connect in-process for tests | mcp<2 (older API, would need porting later) |
| 2026-10-19 | argparse + plain text for the CLI; no Rich | Avoids a new dependency (rules.md); NO_COLOR/80-column rules are easy in plain text | Typer, Rich |
| 2026-10-19 | Offline `HeuristicModel` (MODEL_PROVIDER=heuristic) speaking the same tool-call protocol | Ollama is not installed on the dev laptop; CI and demos still exercise every code path | Only scripted per-test stubs — no way to demo the full flow |
| 2026-10-19 | Schema Inspector and Warehouse Agent are deterministic tool workflows (no model call) | High-precision signals for the aggregator; only the Log Analyst needs reasoning | Three LLM workers — more malformed-call risk on 7B models |
| 2026-10-19 | Risk tier comes from each MCP tool's `meta.risk_tier`; plans may only make a step stricter | The model must never be able to downgrade a DESTRUCTIVE step (S28) | Trusting the planner's tier |
| 2026-10-19 | Approval gate = `request_approval` node + `interrupt_before=["execute"]`; READ-only plans go to `execute_auto` | transient_network must resolve with no human; every gated plan always halts | Dynamic `interrupt()` inside the executor |
| 2026-10-19 | A rejection of ANY gated step means nothing executes, then escalation | Partial fixes are worse than none; BR-09 | Running the approved subset |
| 2026-10-19 | Fork = copy checkpoint state into a NEW thread `<id>-forkN` | Original incident's history and `show` stay unchanged (S40) | Native same-thread fork (moves the thread head) |

## Gotchas & non-obvious behaviour
- Local 7–14B models produce malformed or partial tool-call JSON far more often than hosted models. Expect the model-level retry (BR-05) to fire regularly; track how often in performance.md.
- Jira CSV import: "Story Points" (company-managed) vs. "Story point estimate" (team-managed). Mapping the wrong field imports the points as blank without an error.
- At least one log fixture is deliberately bigger than the model context; that's the test for pagination and the sliding window, not a bug.
- MCP SDK 2.x hides a tool's own exception text unless it raises `ToolError`; `mcp_server/common.py` wraps every tool so "[transient]"/"[permanent]" survives the wire.
- LangGraph `stream_mode="updates"` emits one chunk per node even for parallel workers; prove parallelism from checkpoint history (`snap.next` holds both workers).
- `tests/unit/test_persistence.py` and `tests/e2e/test_persistence.py` share a basename: pytest runs with `--import-mode=importlib`, and helpers are imported via `pythonpath = ["tests"]`.
- Writing shell heredocs through the agent's Bash tool sometimes collapses double backslashes and turns backslash-n into a real newline inside Python strings; edit regexes and newline literals with the editor instead.
- Do not edit repo files while a commit script's test run is in progress: `git add -A` sweeps them into that commit (happened once, see tasks.md).
- DuckDB 1.5: `DATE + BIGINT` is not defined; cast `range()` values to INTEGER.

## Things that were tried and failed
- None yet.

## Environment / access notes
- No network egress beyond localhost is needed or allowed at runtime.
- Model choice is pending S3; until then, any prompt tuning is provisional.
- Ollama was not installed on the dev laptop on 2026-10-19; all runs so far used the heuristic model.

## Stakeholder context
- Framing for client and account-lead audiences: faster MTTR on routine load failures, with a human still signing off on every write.
- The mentor/reviewer cares about verifiable syllabus coverage: TOPICS.md proofs, not demos.

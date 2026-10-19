# Verification — Pipeline Incident Response Agent
<!-- How each task is PROVEN done. Acceptance criteria (what) live in Jira and tasks.md;
     this file says how to check them, what must NOT happen, and what evidence to keep. -->
_Last reviewed: 2026-10-19 · Task IDs match the Jira import and tasks.md · Full suite at a64a8b9: 225 passed, 5 skipped (real-model), ruff clean_

## Rules for verification
1. A task is done only when its check below has been **run**, not reasoned about. Claude must paste the command output summary into the Verification log, not write "tests should pass".
2. Every task has a **negative check** — the thing that must not happen. Passing the positive check alone is not done.
3. Stubbed-model tests prove the plumbing. Any task marked `+ MANUAL` also needs a run against the real local model, because stubs hide the main risk of this project.
4. If a check fails, the task stays IN PROGRESS. Don't weaken the check to make it pass; if the check itself is wrong, change it here and log why in memory.md.

Method key: **AUTO** = pytest · **MANUAL** = run it and observe · **REVIEW** = human reads and judges

Status key: ☑ check run and passed · ◐ automated part passed, MANUAL / real-model part still owed · ☐ not run

## Checks run on every task (Definition of Done)
| Check | Command | Pass condition |
|---|---|---|
| Lint/format | `ruff check . && ruff format --check .` | No errors |
| Full test suite | `pytest -q` | All pass; no new skips without a note in tasks.md |
| No external model or cloud calls | `grep -rnE 'api\.openai|api\.anthropic|bedrock|boto3|snowflake\.connector' src/` | No matches |
| No secrets | `git diff --cached` reviewed; `.env` not staged | Nothing secret staged |
| Docs updated | tasks.md status moved; TOPICS.md Proof filled if this task earns one | Both done |

## Gate 0 — Model viability
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S1 | Repo, env, lint, pytest skeleton | MANUAL | Fresh clone → install command → `ruff check .` → `pytest -q` | Install must not need any manual step that isn't in CLAUDE.md | Terminal output of all three commands; commit hash | ◐ auto part |
| S2 | Ollama smoke test | MANUAL | `ollama list` shows model; `python scripts/smoke_model.py` prints a reply | Script must fail clearly (not hang) when Ollama is stopped — stop it and re-run | Both outputs (running + stopped) | ◐ auto part |
| S3 | Tool-calling benchmark | MANUAL + REVIEW | `python scripts/bench_tools.py --runs 20` for each model | Pass rate must not be counted from a single run; same prompt and temperature for every model | Results table in memory.md decisions log; go/no-go stated | ☐ |
| S4 | Context docs filled | REVIEW | Run PROMPTS.md step 7 (Verify): Claude summarises the app in 5 bullets from docs only | No `<placeholder>` text left: `grep -rn '<' docs/*.md` reviewed by hand | Claude's 5-bullet answer + any gaps fixed | ◐ auto part |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 1 — Mocks and tools
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S5 | DuckDB mock warehouse | AUTO | `pytest tests/unit/test_mocks.py -k warehouse` | Seed must be idempotent: run seed twice, row counts unchanged | Test output | ☑ |
| S6 | Log fixtures, 5 scenarios | AUTO + REVIEW | `pytest tests/unit/test_fixtures.py` (each fixture contains its root-cause signal; one exceeds context budget) | Root-cause line must not be on line 1 or the last line (too easy) | Test output; fixture sizes listed | ☑ |
| S7 | Fake job runner + audit log | AUTO | `pytest tests/unit/test_job_runner.py` | No write tool may touch any file outside the audit DB — test asserts other DB files unchanged | Test output | ☑ |
| S8 | Scenario injector CLI | MANUAL | `python -m incident_agent.cli inject --scenario <id>` for all 5 IDs | Unknown scenario ID must exit non-zero with a clear message | Output of 5 runs + 1 invalid run | ☑ |
| S9 | MCP read tools | AUTO | `pytest tests/unit/test_mcp.py -k read` | fetch_log_window must refuse limit above the configured page size | Test output | ☑ |
| S10 | MCP metadata tools | AUTO | `pytest tests/unit/test_mcp.py -k schema` | compare_source_schema on identical schemas must return no differences | Test output | ☑ |
| S11 | MCP write tools + risk tiers | AUTO | `pytest tests/unit/test_mcp.py -k write` | Every write tool must carry a risk tier — test fails if any tool lacks one | Test output; tool list with tiers | ☑ |
| S12 | MCP client discovery | AUTO | `pytest tests/unit/test_mcp.py::test_mcp_tool_discovery` | Client must not import tool functions directly: `grep -rn 'mcp_server' src/incident_agent/mcp_client/` returns nothing | Test output + grep output | ☑ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 2 — Raw loop (Day 16)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S13 | Raw ReAct loop | AUTO | `pytest tests/unit/test_raw_loop.py` | No framework imports: `test_raw_loop_has_no_framework_imports` greps raw_loop/ for langgraph/langchain | Test output | ☑ |
| S14 | max_iterations guard | AUTO | `pytest tests/unit/test_raw_loop.py::test_raw_loop_respects_max_iterations` | Hitting the limit must not raise; it returns status=incomplete | Test output | ☑ |
| S15 | Model-level re-prompt | AUTO | `pytest tests/unit/test_raw_loop.py::test_malformed_tool_call_reprompted` (stub model returns bad JSON twice) | Third consecutive failure must fail the step, not loop again (BR-05) | Test output; retry count in state | ☑ |
| S16 | Tool-level retry + backoff | AUTO | `pytest tests/unit/test_retry.py` | A permanent error must be attempted exactly once — assert call count == 1 | Test output | ☑ |
| S17 | Log Analyst worker | AUTO + MANUAL | `pytest tests/unit/test_log_analyst.py`; then run against the real local model on schema_drift 5 times | With the real model, root cause must be correct in at least 4 of 5 runs — a stubbed pass alone is not enough | Test output + 5-run tally | ◐ auto part |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 3 — Graph (Day 17, 19)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S18 | IncidentState + reducers | AUTO | `pytest tests/unit/test_state.py` | No node mutates state: test passes a frozen copy and asserts the node returns a dict | Test output | ☑ |
| S19 | Triage node | AUTO + MANUAL | `pytest tests/unit/test_triage.py`; real-model run on all 5 alerts | Malformed alert must yield UNKNOWN, never a guessed type | Test output + 5 classifications | ◐ auto part |
| S20 | Supervisor routing | AUTO | `pytest tests/unit/test_routing.py` — one test per row of the routing table in architecture.md | A worker not in the routing table row must not be invoked (assert call log) | Test output | ☑ |
| S21 | Fallback handler | AUTO | `pytest tests/unit/test_routing.py::test_unknown_alert_routes_to_fallback` and a low-confidence case | Fallback must produce a human-readable summary, not an empty state | Test output; sample escalation text | ☑ |
| S22 | Schema Inspector | AUTO | `pytest tests/unit/test_workers.py -k schema` | Must not report drift on the non-drift scenarios | Test output | ☑ |
| S23 | Warehouse Agent | AUTO | `pytest tests/unit/test_workers.py -k warehouse` | Must not report a suspended warehouse in the late_data scenario (no false positives) | Test output | ☑ |
| S24 | Raw loop as graph node | AUTO | `pytest tests/unit/test_graph_nodes.py -k log_analyst` | raw_loop/ files unchanged: `git diff --stat` on raw_loop/ in this story's PR is empty | Test output + git diff stat | ☑ |
| S25 | Parallel fan-out + merge | AUTO | `pytest tests/unit/test_state.py::test_parallel_workers_findings_merge` | Findings count after fan-out == number of workers run (nothing overwritten) | Test output | ☑ |
| S26 | Supervisor aggregation | AUTO | `pytest tests/unit/test_supervisor.py::test_supervisor_aggregates_three_workers` | Conflicting findings must appear in diagnosis.conflicts, not be silently dropped | Test output | ☑ |
| S27 | Tool-scoping tests | AUTO | `pytest tests/unit/test_tool_scoping.py` | Write tools must not appear in any worker's tool list | Test output | ☑ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 4 — Plan, execute, verify
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S28 | Remediation Planner | AUTO + MANUAL | `pytest tests/unit/test_planner.py`; real-model plan for schema_drift reviewed | Every step must have a risk tier matching the tool's declared tier (planner can't downgrade) | Test output + sample plan JSON | ◐ auto part |
| S29 | Executor | AUTO | `pytest tests/unit/test_executor.py` | After a failed step, later steps must not appear in the audit log | Test output | ☑ |
| S30 | Verify loop | AUTO | `pytest tests/unit/test_verify.py::test_verify_failure_loops_back_once_then_escalates` | Re-diagnose must happen at most once (BR-06): assert verify_attempts <= 2 | Test output | ☑ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 5 — Persistence and memory (Day 18)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S31 | SQLite checkpointer | AUTO | `pytest tests/unit/test_persistence.py`; then `sqlite3 $CHECKPOINT_DB 'select count(*) from checkpoints'` after a run | Two incidents must not share a thread_id | Test output + row count | ☑ |
| S32 | Resume after restart | AUTO + MANUAL | `pytest tests/e2e/test_persistence.py::test_resume_after_process_restart`; manually kill (Ctrl+C) mid-diagnosis and resume | Resumed run must not repeat completed nodes (check node log) | Test output + manual run log | ◐ auto part |
| S33 | Token budgets | AUTO | `pytest tests/unit/test_tokens.py` | Assembling a prompt over budget must raise/trim — never send it | Test output; budgets table in performance.md | ☑ |
| S34 | Sliding window + summary | AUTO | `pytest tests/unit/test_memory.py::test_old_observations_summarised_not_dropped` | Evidence from early observations must still be findable in summary_note | Test output | ☑ |
| S35 | Paginated log fetching | MANUAL | Run the oversized-fixture scenario with token logging on | No prompt in the log exceeds the node budget | Max prompt tokens per node from the run log | ◐ auto part |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 6 — Human in the loop (Day 20)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S36 | Risk-tier policy | AUTO | `pytest tests/unit/test_policy.py` — one case per tier | READ actions must never create an approval request | Test output | ☑ |
| S37 | interrupt_before + CLI | AUTO + MANUAL | `pytest tests/unit/test_hitl.py::test_graph_halts_before_execute`; manual run: approve, reject, edit once each | Pressing Enter alone must reject (design.md); reject must route to escalation (BR-09) | Test output + terminal capture of 3 manual decisions | ◐ auto part |
| S38 | Diff rendering | AUTO + MANUAL | `pytest tests/unit/test_hitl.py::test_destructive_action_requires_diff_approval`; view the prompt with NO_COLOR=1 | Destructive approval must not be possible without the diff having been rendered | Test output + screenshot/capture | ◐ auto part |
| S39 | Durable approvals | MANUAL | Start run → wait at approval → kill process → restart → `cli approvals` → approve | Approved action must execute exactly once (audit log has one row) | Run log + audit log row | ◐ auto part |
| S40 | Time-travel fork | AUTO + MANUAL | `pytest tests/e2e/test_time_travel.py::test_fork_from_checkpoint_changes_plan`; manual `cli checkpoints` + `cli fork` | Original incident's history must be unchanged after the fork | Test output + both plan versions | ◐ auto part |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 7 — Proof
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S41 | E2E tests, 5 scenarios | AUTO | `pytest tests/e2e -q` | No e2e test may use a stubbed model for the diagnosis step in the final run (mark real-model runs; stubs allowed only in CI) | Test output with real model | ◐ auto part |
| S42 | performance.md | REVIEW | Numbers in performance.md reproduced by re-running one scenario | No number without the command that produced it | Re-run output matches within ~20% | ◐ auto part |
| S43 | TOPICS.md proofs | REVIEW | Every Proof cell points to a test that exists and passes: run each named test | No row still prefixed TODO | pytest output for all 16+2 named tests | ☑ |
| S44 | Demo + README | MANUAL | A second person (or a fresh machine) follows README from clone to demo | They must not need to ask you anything — every question = a README fix | Notes from the dry run | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Verification log
<!-- Append one entry per verified task. Newest at the bottom. -->
| Date | ID | Commit | Result | Evidence (summary or link) | Verified by |
|---|---|---|---|---|---|
| 2026-10-19 | S1 | 835a128 | PARTIAL | install + `ruff check .` + `pytest -q` pass in a fresh venv; fresh-clone run not done | Claude |
| 2026-10-19 | S2 | 76f6acd | PARTIAL | Ollama stopped: smoke_model.py exits 1 in ~5 s with a clear message; running case not possible (Ollama not installed) | Claude |
| 2026-10-19 | S3 | e1f4bd8 | NOT RUN | bench_tools.py fails cleanly without Ollama; no pass rates yet | Claude |
| 2026-10-19 | S5 | 9c2feae | PASS | test_mocks.py: 5 passed, seed twice -> identical row counts | Claude |
| 2026-10-19 | S6 | 2867d49 | PASS | test_fixtures.py: root-cause never first/last line; sizes 800/900/1000/1200/6000 lines (late_data ~120k tokens) | Claude |
| 2026-10-19 | S7 | fb384e9 | PASS | test_job_runner.py: warehouse file hash unchanged after writes; replay writes once | Claude |
| 2026-10-19 | S8 | e9793b8 | PASS | 5 scenario injections print [OK]; `--scenario bogus` exits 2 with the valid list | Claude |
| 2026-10-19 | S9 | e5e330b | PASS | test_mcp.py -k read: limit above page size refused as [permanent] | Claude |
| 2026-10-19 | S10 | 86af7bf | PASS | test_mcp.py -k schema: identical schemas -> no differences | Claude |
| 2026-10-19 | S11 | b27bdb4 | PASS | test_mcp.py -k write: every tool has meta.risk_tier (17 tools listed) | Claude |
| 2026-10-19 | S12 | 3c6efd4 | PASS | test_mcp_tool_discovery + stdio transport test; `grep -rn mcp_server src/incident_agent/mcp_client/` -> no matches | Claude |
| 2026-10-19 | S13 | 7b4a04b | PASS | test_raw_loop.py incl. no-framework-imports test | Claude |
| 2026-10-19 | S14 | 7b4a04b | PASS | test_raw_loop_respects_max_iterations: status=incomplete, no raise | Claude |
| 2026-10-19 | S15 | c2efb0f | PASS | test_malformed_tool_call_reprompted; 3rd failure fails the step, no 4th call | Claude |
| 2026-10-19 | S16 | 6d9f5f6 | PASS | test_retry.py: permanent error attempted exactly once | Claude |
| 2026-10-19 | S17 | fd5b533 | PARTIAL | test_log_analyst.py 9 passed (scripted + heuristic, all 5 scenarios); real-model 5-run tally owed | Claude |
| 2026-10-19 | S18 | 873e4d3 | PASS | test_state.py + nodes run on deep-frozen input (test_graph_nodes.py) | Claude |
| 2026-10-19 | S19 | 99096e1 | PARTIAL | test_triage.py 13 passed; malformed -> UNKNOWN without a model call; real-model run owed | Claude |
| 2026-10-19 | S20 | 1f4c1ee | PASS | test_routing.py: one test per table row; non-row workers never sent | Claude |
| 2026-10-19 | S21 | 42ec06a | PASS | fallback summary text asserted for every escalation reason | Claude |
| 2026-10-19 | S22 | ddc1c22 | PASS | no drift reported on the 4 non-drift scenarios | Claude |
| 2026-10-19 | S23 | 31adc7a | PASS | late_data: no SUSPENDED false positive | Claude |
| 2026-10-19 | S24 | 8f93a28 | PASS | test_graph_nodes.py; `git diff --stat` on raw_loop/ empty for the S24 commit | Claude |
| 2026-10-19 | S25 | 9e96f36 | PASS | test_parallel_workers_findings_merge: both workers in one superstep, 2 findings | Claude |
| 2026-10-19 | S26 | 28f7186 | PASS | test_supervisor_aggregates_three_workers: conflicts listed | Claude |
| 2026-10-19 | S27 | 1f810d3 | PASS | test_tool_scoping.py: no write tool in any worker list | Claude |
| 2026-10-19 | S28 | 0ecbe1d | PARTIAL | test_planner.py 11 passed incl. downgrade refused; real-model plan review owed | Claude |
| 2026-10-19 | S29 | cfa80ec | PASS | test_executor.py: after a failed step, later steps absent from audit log | Claude |
| 2026-10-19 | S30 | d3b1a1c | PASS | verify_attempts == 2, two supervisor visits, then escalation | Claude |
| 2026-10-19 | S31 | 3ad4365 | PASS | checkpoints rows >= node transitions; distinct thread ids enforced | Claude |
| 2026-10-19 | S32 | 3ad4365 | PARTIAL | e2e resume after simulated kill: triage/supervisor not re-run; manual Ctrl+C owed | Claude |
| 2026-10-19 | S33 | b76e83b | PASS | test_tokens.py: over-budget prompt trimmed or refused, never sent | Claude |
| 2026-10-19 | S34 | 7dba070 | PASS | test_old_observations_summarised_not_dropped | Claude |
| 2026-10-19 | S35 | 953f721 | PARTIAL | token_report.py (heuristic): max log_analyst prompt 1185 / 6000 tokens; real-model run owed | Claude |
| 2026-10-19 | S36 | b59e429 | PASS | test_policy.py: READ never creates an approval request | Claude |
| 2026-10-19 | S37 | dd5602f | PARTIAL | test_hitl.py: halts before execute; Enter rejects; reject -> escalation; terminal capture owed | Claude |
| 2026-10-19 | S38 | c739ae7 | PARTIAL | DiffNotShownError until diff rendered; NO_COLOR output has no ANSI, <= 80 cols; screenshot owed | Claude |
| 2026-10-19 | S39 | 19529d3 | PARTIAL | e2e: approval survives process exit, executes exactly once (one audit row per action); manual kill/restart owed | Claude |
| 2026-10-19 | S40 | 7ab113c | PARTIAL | test_fork_from_checkpoint_changes_plan: original history unchanged; CLI checkpoints/fork run once by hand in this session | Claude |
| 2026-10-19 | S41 | 53f5d00 | PARTIAL | tests/e2e: 5 scenarios resolve with heuristic model; RUN_REAL_MODEL=1 run owed | Claude |
| 2026-10-19 | S42 | da04492 | PARTIAL | performance.md heuristic numbers reproduced within noise on re-run; real-model numbers owed | Claude |
| 2026-10-19 | S43 | 60b07fd | PASS | every TOPICS.md proof test run: 33 passed | Claude |
| 2026-10-19 | S44 | a64a8b9 | NOT RUN | README written; second-person dry run owed | Claude |

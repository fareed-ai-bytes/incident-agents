# Verification — Pipeline Incident Response Agent
<!-- How each task is PROVEN done. Acceptance criteria (what) live in Jira and tasks.md;
     this file says how to check them, what must NOT happen, and what evidence to keep. -->
_Last reviewed: 2026-10-19 · Task IDs match the Jira import and tasks.md_

## Rules for verification
1. A task is done only when its check below has been **run**, not reasoned about. Claude must paste the command output summary into the Verification log, not write "tests should pass".
2. Every task has a **negative check** — the thing that must not happen. Passing the positive check alone is not done.
3. Stubbed-model tests prove the plumbing. Any task marked `+ MANUAL` also needs a run against the real local model, because stubs hide the main risk of this project.
4. If a check fails, the task stays IN PROGRESS. Don't weaken the check to make it pass; if the check itself is wrong, change it here and log why in memory.md.

Method key: **AUTO** = pytest · **MANUAL** = run it and observe · **REVIEW** = human reads and judges

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
| S1 | Repo, env, lint, pytest skeleton | MANUAL | Fresh clone → install command → `ruff check .` → `pytest -q` | Install must not need any manual step that isn't in CLAUDE.md | Terminal output of all three commands; commit hash | ☐ |
| S2 | Ollama smoke test | MANUAL | `ollama list` shows model; `python scripts/smoke_model.py` prints a reply | Script must fail clearly (not hang) when Ollama is stopped — stop it and re-run | Both outputs (running + stopped) | ☐ |
| S3 | Tool-calling benchmark | MANUAL + REVIEW | `python scripts/bench_tools.py --runs 20` for each model | Pass rate must not be counted from a single run; same prompt and temperature for every model | Results table in memory.md decisions log; go/no-go stated | ☐ |
| S4 | Context docs filled | REVIEW | Run PROMPTS.md step 7 (Verify): Claude summarises the app in 5 bullets from docs only | No `<placeholder>` text left: `grep -rn '<' docs/*.md` reviewed by hand | Claude's 5-bullet answer + any gaps fixed | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 1 — Mocks and tools
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S5 | DuckDB mock warehouse | AUTO | `pytest tests/unit/test_mocks.py -k warehouse` | Seed must be idempotent: run seed twice, row counts unchanged | Test output | ☐ |
| S6 | Log fixtures, 5 scenarios | AUTO + REVIEW | `pytest tests/unit/test_fixtures.py` (each fixture contains its root-cause signal; one exceeds context budget) | Root-cause line must not be on line 1 or the last line (too easy) | Test output; fixture sizes listed | ☐ |
| S7 | Fake job runner + audit log | AUTO | `pytest tests/unit/test_job_runner.py` | No write tool may touch any file outside the audit DB — test asserts other DB files unchanged | Test output | ☐ |
| S8 | Scenario injector CLI | MANUAL | `python -m incident_agent.cli inject --scenario <id>` for all 5 IDs | Unknown scenario ID must exit non-zero with a clear message | Output of 5 runs + 1 invalid run | ☐ |
| S9 | MCP read tools | AUTO | `pytest tests/unit/test_mcp.py -k read` | fetch_log_window must refuse limit above the configured page size | Test output | ☐ |
| S10 | MCP metadata tools | AUTO | `pytest tests/unit/test_mcp.py -k schema` | compare_source_schema on identical schemas must return no differences | Test output | ☐ |
| S11 | MCP write tools + risk tiers | AUTO | `pytest tests/unit/test_mcp.py -k write` | Every write tool must carry a risk tier — test fails if any tool lacks one | Test output; tool list with tiers | ☐ |
| S12 | MCP client discovery | AUTO | `pytest tests/unit/test_mcp.py::test_mcp_tool_discovery` | Client must not import tool functions directly: `grep -rn 'mcp_server' src/incident_agent/mcp_client/` returns nothing | Test output + grep output | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 2 — Raw loop (Day 16)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S13 | Raw ReAct loop | AUTO | `pytest tests/unit/test_raw_loop.py` | No framework imports: `test_raw_loop_has_no_framework_imports` greps raw_loop/ for langgraph/langchain | Test output | ☐ |
| S14 | max_iterations guard | AUTO | `pytest tests/unit/test_raw_loop.py::test_raw_loop_respects_max_iterations` | Hitting the limit must not raise; it returns status=incomplete | Test output | ☐ |
| S15 | Model-level re-prompt | AUTO | `pytest tests/unit/test_raw_loop.py::test_malformed_tool_call_reprompted` (stub model returns bad JSON twice) | Third consecutive failure must fail the step, not loop again (BR-05) | Test output; retry count in state | ☐ |
| S16 | Tool-level retry + backoff | AUTO | `pytest tests/unit/test_retry.py` | A permanent error must be attempted exactly once — assert call count == 1 | Test output | ☐ |
| S17 | Log Analyst worker | AUTO + MANUAL | `pytest tests/unit/test_log_analyst.py`; then run against the real local model on schema_drift 5 times | With the real model, root cause must be correct in at least 4 of 5 runs — a stubbed pass alone is not enough | Test output + 5-run tally | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 3 — Graph (Day 17, 19)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S18 | IncidentState + reducers | AUTO | `pytest tests/unit/test_state.py` | No node mutates state: test passes a frozen copy and asserts the node returns a dict | Test output | ☐ |
| S19 | Triage node | AUTO + MANUAL | `pytest tests/unit/test_triage.py`; real-model run on all 5 alerts | Malformed alert must yield UNKNOWN, never a guessed type | Test output + 5 classifications | ☐ |
| S20 | Supervisor routing | AUTO | `pytest tests/unit/test_routing.py` — one test per row of the routing table in architecture.md | A worker not in the routing table row must not be invoked (assert call log) | Test output | ☐ |
| S21 | Fallback handler | AUTO | `pytest tests/unit/test_routing.py::test_unknown_alert_routes_to_fallback` and a low-confidence case | Fallback must produce a human-readable summary, not an empty state | Test output; sample escalation text | ☐ |
| S22 | Schema Inspector | AUTO | `pytest tests/unit/test_workers.py -k schema` | Must not report drift on the non-drift scenarios | Test output | ☐ |
| S23 | Warehouse Agent | AUTO | `pytest tests/unit/test_workers.py -k warehouse` | Must not report a suspended warehouse in the late_data scenario (no false positives) | Test output | ☐ |
| S24 | Raw loop as graph node | AUTO | `pytest tests/unit/test_graph_nodes.py -k log_analyst` | raw_loop/ files unchanged: `git diff --stat` on raw_loop/ in this story's PR is empty | Test output + git diff stat | ☐ |
| S25 | Parallel fan-out + merge | AUTO | `pytest tests/unit/test_state.py::test_parallel_workers_findings_merge` | Findings count after fan-out == number of workers run (nothing overwritten) | Test output | ☐ |
| S26 | Supervisor aggregation | AUTO | `pytest tests/unit/test_supervisor.py::test_supervisor_aggregates_three_workers` | Conflicting findings must appear in diagnosis.conflicts, not be silently dropped | Test output | ☐ |
| S27 | Tool-scoping tests | AUTO | `pytest tests/unit/test_tool_scoping.py` | Write tools must not appear in any worker's tool list | Test output | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 4 — Plan, execute, verify
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S28 | Remediation Planner | AUTO + MANUAL | `pytest tests/unit/test_planner.py`; real-model plan for schema_drift reviewed | Every step must have a risk tier matching the tool's declared tier (planner can't downgrade) | Test output + sample plan JSON | ☐ |
| S29 | Executor | AUTO | `pytest tests/unit/test_executor.py` | After a failed step, later steps must not appear in the audit log | Test output | ☐ |
| S30 | Verify loop | AUTO | `pytest tests/unit/test_verify.py::test_verify_failure_loops_back_once_then_escalates` | Re-diagnose must happen at most once (BR-06): assert verify_attempts <= 2 | Test output | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 5 — Persistence and memory (Day 18)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S31 | SQLite checkpointer | AUTO | `pytest tests/unit/test_persistence.py`; then `sqlite3 $CHECKPOINT_DB 'select count(*) from checkpoints'` after a run | Two incidents must not share a thread_id | Test output + row count | ☐ |
| S32 | Resume after restart | AUTO + MANUAL | `pytest tests/e2e/test_persistence.py::test_resume_after_process_restart`; manually kill (Ctrl+C) mid-diagnosis and resume | Resumed run must not repeat completed nodes (check node log) | Test output + manual run log | ☐ |
| S33 | Token budgets | AUTO | `pytest tests/unit/test_tokens.py` | Assembling a prompt over budget must raise/trim — never send it | Test output; budgets table in performance.md | ☐ |
| S34 | Sliding window + summary | AUTO | `pytest tests/unit/test_memory.py::test_old_observations_summarised_not_dropped` | Evidence from early observations must still be findable in summary_note | Test output | ☐ |
| S35 | Paginated log fetching | MANUAL | Run the oversized-fixture scenario with token logging on | No prompt in the log exceeds the node budget | Max prompt tokens per node from the run log | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 6 — Human in the loop (Day 20)
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S36 | Risk-tier policy | AUTO | `pytest tests/unit/test_policy.py` — one case per tier | READ actions must never create an approval request | Test output | ☐ |
| S37 | interrupt_before + CLI | AUTO + MANUAL | `pytest tests/unit/test_hitl.py::test_graph_halts_before_execute`; manual run: approve, reject, edit once each | Pressing Enter alone must reject (design.md); reject must route to escalation (BR-09) | Test output + terminal capture of 3 manual decisions | ☐ |
| S38 | Diff rendering | AUTO + MANUAL | `pytest tests/unit/test_hitl.py::test_destructive_action_requires_diff_approval`; view the prompt with NO_COLOR=1 | Destructive approval must not be possible without the diff having been rendered | Test output + screenshot/capture | ☐ |
| S39 | Durable approvals | MANUAL | Start run → wait at approval → kill process → restart → `cli approvals` → approve | Approved action must execute exactly once (audit log has one row) | Run log + audit log row | ☐ |
| S40 | Time-travel fork | AUTO + MANUAL | `pytest tests/e2e/test_time_travel.py::test_fork_from_checkpoint_changes_plan`; manual `cli checkpoints` + `cli fork` | Original incident's history must be unchanged after the fork | Test output + both plan versions | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Gate 7 — Proof
| ID | Task | Method | How to verify | Must NOT happen | Evidence to keep | Status |
|---|---|---|---|---|---|---|
| S41 | E2E tests, 5 scenarios | AUTO | `pytest tests/e2e -q` | No e2e test may use a stubbed model for the diagnosis step in the final run (mark real-model runs; stubs allowed only in CI) | Test output with real model | ☐ |
| S42 | performance.md | REVIEW | Numbers in performance.md reproduced by re-running one scenario | No number without the command that produced it | Re-run output matches within ~20% | ☐ |
| S43 | TOPICS.md proofs | REVIEW | Every Proof cell points to a test that exists and passes: run each named test | No row still prefixed TODO | pytest output for all 16+2 named tests | ☐ |
| S44 | Demo + README | MANUAL | A second person (or a fresh machine) follows README from clone to demo | They must not need to ask you anything — every question = a README fix | Notes from the dry run | ☐ |

**Gate exit:** all tasks above ☑, and the full `pytest -q` run is green on the gate's last commit.

## Verification log
<!-- Append one entry per verified task. Newest at the bottom. -->
| Date | ID | Commit | Result | Evidence (summary or link) | Verified by |
|---|---|---|---|---|---|
| YYYY-MM-DD | S1 | abc1234 | PASS | ruff clean; 1 passed | Fareed / Claude |

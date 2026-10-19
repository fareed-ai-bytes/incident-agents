# Syllabus coverage — Pipeline Incident Response Agent

## Work Version 1 — Week 4 (Days 16–20): agentic systems, LangGraph, persistence, multi-agent + MCP, human-in-the-loop

_Claude: fill the "Proof" column as tasks finish — a test name (`tests/...::test_x`) or a docs/performance.md section. A topic without proof is not done. Until then, Proof shows the target, prefixed TODO._

_Proofs verified 2026-10-19: every named test was run and passed (33 passed, `pytest -v <each test>`). Stubbed/heuristic models prove the plumbing; rows tagged (real-model pending) still need the MANUAL run in verification.md._

| # | Topic | Where it lives in this app | Task | Proof |
|---|---|---|---|---|
| 1 | Reason-Act-Observe (ReAct) | Log Analyst: thought → fetch_log_window → observe → narrow the range → conclude | S13, S17 | `tests/unit/test_log_analyst.py::test_log_analyst_finds_root_cause_schema_drift` (real-model pending, S17) |
| 2 | Plan-and-Execute | Planner emits ordered steps; executor runs them one by one | S28, S29 | `tests/unit/test_planner.py::test_plan_has_ordered_steps_with_risk_tier` |
| 3 | Raw SDK execution | `raw_loop/` against Ollama's OpenAI-compatible API, no framework imports | S13, S14 | `tests/unit/test_raw_loop.py::test_raw_loop_respects_max_iterations` (+ `test_raw_loop_has_no_framework_imports`) |
| 4 | Conditional routing | Supervisor routes by alert type; fallback on unknown or low confidence | S20, S21 | `tests/unit/test_routing.py::test_unknown_alert_routes_to_fallback` |
| 5 | State machines | Top-level StateGraph: triage → diagnose → plan → approve → execute → verify | S18 | graph diagram in `docs/architecture.md` + `tests/unit/test_graph_compiles.py::test_graph_compiles_with_expected_nodes` |
| 6 | Reducers | `messages` add_messages; `findings` list-append; nodes return dict updates only | S18, S25 | `tests/unit/test_state.py::test_parallel_workers_findings_merge` |
| 7 | Conditional edges | Verify: healthy → END; failing → re-diagnose once → escalate | S30 | `tests/unit/test_verify.py::test_verify_failure_loops_back_once_then_escalates` |
| 8 | SQLite persistence | SqliteSaver checkpointer, thread_id per incident | S31, S32 | `tests/e2e/test_persistence.py::test_resume_after_process_restart` |
| 9 | Sliding window pruning | Last N observations verbatim; older ones summarised into summary_note | S34 | `tests/unit/test_memory.py::test_old_observations_summarised_not_dropped` |
| 10 | Token limits | Per-node budgets; paginated log fetches | S33, S35 | `docs/performance.md` § Token budget + `tests/unit/test_tokens.py` + `tests/unit/test_pagination.py` |
| 11 | Supervisor routing | Incident Commander delegates and aggregates | S20, S26 | `tests/unit/test_supervisor.py::test_supervisor_aggregates_three_workers` |
| 12 | Worker delegation | Log Analyst / Schema Inspector / Warehouse Agent, each with scoped tools | S22–S24, S27 | `tests/unit/test_tool_scoping.py` (one test per worker) |
| 13 | Model Context Protocol (MCP) | Local MCP server over stdio; tools discovered at runtime | S9–S12 | `tests/unit/test_mcp.py::test_mcp_tool_discovery` (+ `test_stdio_transport_discovers_tools`) |
| 14 | State interrupts | `interrupt_before=["execute"]` for gated steps | S37 | `tests/unit/test_hitl.py::test_graph_halts_before_execute` |
| 15 | Approval gates | Risk tiers BR-01; diff for destructive actions; approvals durable across restart | S36, S38, S39 | `tests/unit/test_hitl.py::test_destructive_action_requires_diff_approval` (+ `tests/e2e/test_durable_approvals.py`) |
| 16 | Time-traveling | List checkpoints; fork from post-diagnosis with an edited hypothesis | S40 | `tests/e2e/test_time_travel.py::test_fork_from_checkpoint_changes_plan` |

### Beyond the syllabus (project spec)
| Item | Where | Task | Proof |
|---|---|---|---|
| Automated retries (tool-level) | Backoff on transient errors | S16 | `tests/e2e/test_scenarios.py::test_transient_network_resolves_without_human` (+ `tests/unit/test_retry.py`) |
| Automated retries (model-level) | Re-prompt on malformed tool calls | S15 | `tests/unit/test_raw_loop.py::test_malformed_tool_call_reprompted` |

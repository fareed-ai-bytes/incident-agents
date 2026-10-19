# Architecture — Pipeline Incident Response Agent
_Last reviewed: 2026-10-19 · Status: built (S1–S44). Real-model checks still pending — see verification.md_

## Stack
| Layer | Technology | Version | Notes |
|---|---|---|---|
| Language | Python | 3.11+ (dev: 3.11.3) | |
| Orchestration | LangGraph | 1.2.16 | StateGraph, Send fan-out, conditional edges, interrupt_before |
| Persistence | langgraph-checkpoint-sqlite + SQLite audit DB | 3.1.2 | One thread_id per incident |
| Model serving | Ollama (OpenAI-compatible endpoint) via httpx | httpx 0.28.1 | Model chosen by S3 benchmark (pending); `heuristic` offline stand-in for CI |
| Tool protocol | MCP Python SDK (`MCPServer`/`Client`), stdio transport | mcp 2.3.0 | Local server process; in-process in unit tests |
| Mock warehouse | DuckDB | 1.5.6 | Stand-in for Snowflake |
| Mock logs | Generated text fixtures | — | 5 scenarios, `mocks/fixtures_gen.py` |
| Interface | CLI (argparse, plain text) | — | No web UI in v1; Rich not added |
| Tests | pytest, ruff | 9.1.1, 0.17.1 | |

## System overview
The scenario injector emits an alert. The LangGraph graph triages the alert and the supervisor routes it to specialist workers, which run in parallel and call tools discovered from the local MCP server. The supervisor aggregates their findings, then the planner drafts an ordered remediation plan. Before the executor runs, any gated step triggers an interrupt that waits for a human decision, stored in SQLite so it can be resumed hours later. The executor calls write tools, which only record to the fake job runner's audit log. The verify node then ends the incident, loops back once to re-diagnose, or escalates. Every node transition is checkpointed.

```mermaid
flowchart TD
  A[Scenario injector / alert] --> T[Triage]
  T -->|known type| S{Supervisor router}
  T -->|unknown| F[Fallback escalation]
  S --> LA[Log Analyst<br/>raw ReAct loop]
  S --> SI[Schema Inspector]
  S --> WA[Warehouse Agent]
  LA --> AG[Supervisor aggregate]
  SI --> AG
  WA --> AG
  AG -->|confidence < threshold| F
  AG --> P[Remediation Planner]
  P -->|READ-only plan| XA[execute_auto]
  P -->|gated steps| RA[request_approval]
  P -->|no valid plan| F
  RA --> G{Approval gate<br/>interrupt_before execute}
  G -->|approved| X[Executor]
  G -->|rejected / expired| F
  X --> V{Verify}
  XA --> V
  X -->|step failed| F
  V -->|healthy| E[END]
  V -->|failing, first time| S
  V -->|failing again| F
  subgraph Local only
    MCP[(MCP server<br/>stdio)]
    OL[(Ollama)]
    DB[(SQLite checkpoints + audit)]
  end
```

## Directory map
```
src/incident_agent/
  graph/       # StateGraph definition, nodes, routing functions, state schema
  agents/      # worker agents; log_analyst uses the raw loop
  raw_loop/    # framework-free ReAct loop, retries, max_iterations (no LangGraph imports)
  mcp_server/  # MCP server exposing read, metadata and write tools
  mcp_client/  # tool discovery and schema conversion
  mocks/       # DuckDB seed, log fixtures, fake job runner, scenario injector
  policy/      # risk tiers, token budgets, durable approval store
  llm/         # Ollama client (localhost only) + deterministic heuristic model
  cli/         # seed, inject, run, approvals, show, checkpoints, fork, resume
tests/
  unit/        # per-module tests
  e2e/         # one test per scenario
docs/          # this documentation set
```

## Key components
| Component | Responsibility | Depends on |
|---|---|---|
| Triage node | Classify an alert into an AlertType | Ollama |
| Supervisor router | Choose workers per alert type; handle the fallback route | IncidentState |
| Log Analyst | Iteratively read paginated logs to find the root cause (raw ReAct loop) | MCP log tools, Ollama |
| Schema Inspector | Detect source vs. warehouse schema drift | MCP metadata tools |
| Warehouse Agent | Check load audit, warehouse status, partition arrival | MCP warehouse tools |
| Aggregator | Merge findings into a single diagnosis with confidence; flag conflicts | findings reducer |
| Planner | Produce a schema-valid ordered plan with risk tiers | Ollama, policy |
| Approval gate | Interrupt before gated steps; show diff; record decision | policy, SQLite |
| Executor | Run plan steps in order; stop on failure | MCP write tools |
| Verify node | Re-check health; route to end, re-diagnose or escalate | MCP read tools |
| Fake job runner | Record write actions; simulate transient failures | SQLite audit DB |

### Routing table (FR-02)
| AlertType | Workers |
|---|---|
| SCHEMA_DRIFT | Log Analyst, Schema Inspector |
| AUTH_FAILURE | Log Analyst |
| WAREHOUSE_UNAVAILABLE | Warehouse Agent, Log Analyst |
| LATE_DATA | Warehouse Agent, Log Analyst |
| TRANSIENT_NETWORK | Log Analyst (retries are expected to resolve it) |
| UNKNOWN | Fallback |

## Data model
- **IncidentState** (LangGraph state)
  - `incident_id`, `alert`, `alert_type`
  - `messages` (reducer: add_messages)
  - `findings` (reducer: list append): each has worker, root_cause, evidence[], confidence
  - `diagnosis`: root_cause, confidence, conflicts[]
  - `plan`: ordered steps, each with tool, args, risk_tier, rationale
  - `step_results`, `retry_counts`, `verify_attempts`
  - `summary_note`: rolling summary for the sliding window
- **SQLite checkpoints**: managed by the LangGraph checkpointer, keyed by thread_id = incident_id.
- **audit_log** (SQLite): id, incident_id, action, args_json, risk_tier, approver, approval_id, step_index, decision, status, result_json, timestamp. Unique per (incident, approval, step, action), so a replayed step never writes twice.
- **approvals** (SQLite, same file): one row per gated step, PENDING -> APPROVED / REJECTED / EXPIRED, with approver and decided_at.
- **Mock warehouse** (DuckDB): 3+ business tables and a `load_audit` table.

## External integrations
| System | Purpose | Auth method | Failure behaviour |
|---|---|---|---|
| Ollama (localhost) | LLM inference | None (local) | Retry once, then fail the node with a clear error |
| MCP server (stdio, local) | Tool discovery and execution | None (local process) | Transient → backoff retry; permanent → finding marked failed |
| DuckDB file | Mock warehouse | File path | Fail fast: a setup error, not an incident |

## Environments & config
- Env vars live in `.env` (gitignored); `.env.example` is committed. Keys: `MODEL_PROVIDER`, `MODEL_NAME`, `OLLAMA_BASE_URL`, `CHECKPOINT_DB`, `AUDIT_DB`, `WAREHOUSE_DB`, `MAX_ITERATIONS`, `CONFIDENCE_THRESHOLD`, `LOG_PAGE_SIZE`, `APPROVAL_TTL_HOURS`, `LOG_LEVEL`.
- Environments: local only. There is no dev or prod in v1.

## Architecture decisions (short form — detail in memory.md)
- Local models only — client data cannot leave the environment.
- Mocked backends — the project stays reproducible and no hallucinated write can touch real systems.
- The Log Analyst is a raw SDK loop wrapped as a node — this covers Day 16 mechanics inside a Day 17 graph.
- Tools go through MCP rather than direct imports — workers are scoped by which tools they're given.

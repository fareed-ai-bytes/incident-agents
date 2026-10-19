# incident-agent — Pipeline Incident Response Agent

A multi-agent [LangGraph](https://langchain-ai.github.io/langgraph/) system that triages failed
data-pipeline loads, diagnoses the root cause with specialist agents, plans a fix, and runs write
actions **only after a human approves them**. Everything runs locally: models on Ollama, tools on a
local MCP server, and mocked backends (DuckDB, log fixtures, a fake job runner).

```
alert ─► triage ─► supervisor ─┬─► Log Analyst (raw ReAct loop) ─┐
                               ├─► Schema Inspector              ├─► aggregate ─► planner
                               └─► Warehouse Agent ──────────────┘                  │
            ┌────────────────────── READ-only plan ─────────────────────────────────┤
            ▼                                                                       ▼
      execute_auto                                      request_approval ─╳─► execute
            └──────────────────────────► verify ◄───────────────────────────────────┘
                     healthy ─► END · failing once ─► supervisor · again ─► fallback
```
`╳` = `interrupt_before=["execute"]`: the graph halts and waits for a decision stored in SQLite.
Full diagram and component list: [docs/architecture.md](docs/architecture.md).

## Quickstart (5 minutes, no model needed)

Requires Python 3.11+.

```bash
python -m venv .venv
```
Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` elsewhere), then:

```bash
pip install -e ".[dev]"
```
```bash
python -m incident_agent.cli seed
```
```bash
python -m incident_agent.cli run --scenario schema_drift --model heuristic
```

`--model heuristic` uses a deterministic offline stand-in for the LLM so you can see the whole
flow without Ollama. In a terminal you are asked to approve each write step:

```
Step 1: alter_table [DESTRUCTIVE]
    Diff:
      --- before
      +++ after
      ...
      -  created_at TIMESTAMP
      +  created_at TIMESTAMP,
      +  loyalty_tier VARCHAR
[a]pprove / [r]eject / [e]dit (default: reject):
```
Pressing Enter alone **rejects** and the incident is escalated with a written summary.

Try the other scenarios: `auth_failure`, `warehouse_unavailable`, `late_data`,
`transient_network` (this one resolves with no human input: its plan is READ-only and the tool
layer retries the transient errors).

## Running with a real local model

```bash
ollama serve
```
```bash
ollama pull qwen2.5:7b-instruct
```
```bash
python scripts/smoke_model.py
```
```bash
python scripts/bench_tools.py --runs 20 --models qwen2.5:7b-instruct llama3.1:8b
```
Copy `.env.example` to `.env` and set `MODEL_NAME` to the model the benchmark picks. The
endpoint must be `localhost` — the app refuses any other host.

## Commands

| Command | What it does |
|---|---|
| `seed` | (Re)create the DuckDB mock warehouse and the SQLite audit DB |
| `inject --scenario X` | Print the alert for a scenario |
| `run --scenario X [--model M] [--no-input]` | Run a scenario; prompts for approval in a terminal |
| `approvals [--incident ID]` | Pending approvals across incidents, oldest first, with age |
| `show <incident> [--verbose]` | Incident view: header, diagnosis, evidence, plan, pending action |
| `checkpoints <incident>` | Every checkpoint of an incident |
| `fork <incident> <#> --category X` | Re-run from a checkpoint with an edited diagnosis (new incident) |
| `resume <incident>` | Continue an incident interrupted by a crash |

All commands: `python -m incident_agent.cli <command>`. Approver name: `--approver`, or
`$INCIDENT_APPROVER`, or your login name.

## Safety rules the code enforces

- **Risk tiers (BR-01)** come from each MCP tool's declared `meta.risk_tier`; a plan can make a
  step stricter, never looser. READ runs automatically; REVERSIBLE needs an approval; DESTRUCTIVE
  needs an approval *and* its diff must have been rendered first.
- The fake job runner refuses gated writes without an approver + approval id, and replaying a step
  never writes twice.
- Rejections (BR-09), expired approvals after 24 h (BR-08), failed steps and a second failed
  verification (BR-06) all end in an escalation summary — never a silent stop.
- Loops are bounded: 6 ReAct iterations (BR-02), 2 re-prompts per malformed tool call (BR-05),
  3 tool attempts with backoff for transient errors only (BR-04), per-node token budgets (BR-07).
- No hosted LLMs and no real cloud clients; everything is mocked and local.

## Tests

```bash
pytest -q
```
```bash
ruff check . && ruff format --check .
```
Tests use temporary databases and the offline model; the MCP tests also spawn the real stdio
server. `scripts/token_report.py` prints prompt sizes per node and timings
([docs/performance.md](docs/performance.md)).

## Layout

```
src/incident_agent/
  graph/       StateGraph, nodes, routing, state + reducers, runner (SQLite), HITL sessions
  agents/      Log Analyst (raw loop), Schema Inspector, Warehouse Agent; prompts/ per agent
  raw_loop/    framework-free ReAct loop, retry, sliding-window memory, token budgets
  mcp_server/  local MCP server: read, metadata and write tools with risk tiers
  mcp_client/  runtime discovery, per-worker scoping, schema validation
  mocks/       DuckDB warehouse, generated log fixtures, fake job runner, injector
  policy/      risk tiers, token budgets, durable approval store
  llm/         Ollama client (httpx, localhost only) and the offline heuristic model
  cli/         argparse CLI and plain-text rendering
docs/          product, architecture, rules, design, tasks, verification, TOPICS, performance
```

## Status

All 44 backlog stories are implemented with automated tests. Checks that need a real local
model or a human at a terminal are still open — see [docs/tasks.md](docs/tasks.md) and
[docs/verification.md](docs/verification.md).

## License

GPL-3.0 — see [LICENSE](LICENSE).

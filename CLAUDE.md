# CLAUDE.md — Pipeline Incident Response Agent

<!-- This is the ONLY file Claude Code loads automatically. Keep it under ~100 lines.
     Everything else is pulled in via @imports below or read on demand. -->

## What this is
A multi-agent LangGraph system, running on local open models, that triages failed data-pipeline loads, diagnoses the root cause with specialist agents, plans remediation, and executes write actions only after human approval. Built for on-call data engineers and their approvers.

## Always-loaded context
- Product requirements: @docs/product.md
- Architecture: @docs/architecture.md
- Coding & business rules: @docs/rules.md
- Project memory (decisions, gotchas): @docs/memory.md

## Read on demand (not auto-loaded — too volatile or too big)
- CLI/UX direction: `docs/design.md` — read before touching any CLI output or approval prompt
- Tasks & progress: `docs/tasks.md` — read at session start, update at session end
- Syllabus coverage: `docs/TOPICS.md` — update the Proof column when a task closes

## Hard constraints (never violate)
- All model calls go to the LOCAL Ollama endpoint. Never add a hosted LLM API.
- All backends are MOCKS (DuckDB, JSON log fixtures, fake job runner). Never add real AWS, Snowflake or Fivetran clients.
- Write tools must never execute without passing the approval gate (see BR-01 in rules.md).

## Commands (confirmed in S1 — Python 3.11, argparse CLI, plain-text output)
- Install: `pip install -e ".[dev]"` (or `uv venv && uv pip install -e ".[dev]"`)
- Start model: `ollama serve` then `ollama pull $MODEL_NAME`
- Seed mocks: `python -m incident_agent.mocks.seed`
- Inject an alert: `python -m incident_agent.cli inject --scenario schema_drift`
- Run a scenario: `python -m incident_agent.cli run --scenario schema_drift` (add `--model heuristic` to run offline)
- Approve pending actions: `python -m incident_agent.cli approvals`
- Inspect: `python -m incident_agent.cli show <incident>` · `checkpoints <incident>` · `fork <incident> <checkpoint>`
- Test: `pytest -q`
- Lint/format: `ruff check . && ruff format --check .`

## Session protocol
1. At start: read `docs/tasks.md`, pick up the item marked IN PROGRESS.
2. Before any change touching >3 files: state the plan, wait for approval.
3. At end: update `docs/tasks.md` status; append any new decision or gotcha to `docs/memory.md`; fill any newly earned Proof in `docs/TOPICS.md`.
4. If a rule in `docs/rules.md` conflicts with a request, flag it — do not silently pick one.
5. Task IDs (S1–S44) match the Jira import file. Reference them in commits.

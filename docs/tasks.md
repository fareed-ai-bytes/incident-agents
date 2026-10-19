# Tasks & Progress — Pipeline Incident Response Agent
_Claude: update this at the end of every session. Keep DONE to the last ~10 items; archive older ones._
_Task IDs match the Jira import (incident_agent_jira_import.csv). Full acceptance criteria live in Jira; the summaries here are for session pickup._

## Current focus
Gate 0: prove a local model can drive tool calls (S1–S3) before building anything else. Target: end of Day 16.

## IN PROGRESS
- [ ] S1 Set up repo, Python env, linting and pytest skeleton — not started; next: pin Python and LangGraph versions, update CLAUDE.md commands

## TODO (prioritised, top = next)
### Gate 0 — model viability (do not start Gate 1 until S3 records a decision)
- [ ] S2 Install Ollama and smoke-test local endpoint — acceptance: script prints a reply from the configured model
- [ ] S3 Benchmark tool-calling of 2+ local models, 20 runs each — acceptance: pass rates and chosen model in memory.md; go/no-go threshold met
- [ ] S4 Fill context docs — acceptance: placeholders resolved or moved to Open questions

### Gate 1 — mocks and tools (Day 16–19)
- [ ] S5 DuckDB mock warehouse — refs: FR-03
- [ ] S6 Log fixtures for 5 scenarios — refs: FR-01, BR-07
- [ ] S7 Fake job runner + audit log — refs: FR-07, FR-10
- [ ] S8 Scenario injector CLI
- [ ] S9–S12 MCP server (read, metadata, write tools) + client discovery — refs: FR-14, BR-01

### Gate 2 — raw loop (Day 16)
- [ ] S13 Raw ReAct loop, no framework
- [ ] S14 max_iterations guard — refs: BR-02
- [ ] S15 Malformed tool-call re-prompt — refs: FR-11, BR-05
- [ ] S16 Tool-level retry with backoff — refs: FR-10, BR-04
- [ ] S17 Log Analyst worker

### Gate 3 — graph (Day 17, 19)
- [ ] S18–S26 State + reducers, triage, routing, fallback, workers, fan-out, aggregation — refs: FR-01, FR-02, FR-04, FR-05
- [ ] S27 Tool-scoping tests per worker

### Gate 4 — plan, execute, verify (Day 16–17)
- [ ] S28–S30 Planner, executor, verify loop — refs: FR-06, FR-12, BR-06

### Gate 5 — persistence and memory (Day 18)
- [ ] S31–S35 SQLite checkpointer, restart resume, token budgets, sliding window, paginated logs — refs: FR-09, BR-07

### Gate 6 — human in the loop (Day 20)
- [ ] S36–S40 Risk policy, interrupt + CLI, diff rendering, durable approvals, time-travel — refs: FR-07, FR-08, FR-09, FR-13, BR-01, BR-08, BR-09

### Gate 7 — proof
- [ ] S41–S44 E2E tests, performance.md, TOPICS.md proofs, demo + README

## BLOCKED
- [ ] S17 onward — blocked by: the S3 model decision (if no model passes, the design changes; see Open questions in product.md)

## DONE (recent)
- [x] Use case selected and backlog created (Jira CSV, 44 stories, 77 pts) — 2026-10-19
- [x] Context docs drafted — 2026-10-19

## Known bugs / tech debt
- Backlog is 77 points against a ~1-week window — impact: Gates 5–7 at risk — area: planning. Decide on cuts after S3.
- Confidence threshold, page size and approval expiry are placeholders — impact: tuned values may change routing behaviour — area: rules.md BR-03, BR-07, BR-08

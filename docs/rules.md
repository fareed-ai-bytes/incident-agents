# Rules — Pipeline Incident Response Agent
<!-- Every rule must be verifiable. "Write clean code" is not a rule. -->

## Coding rules
### Style
- Python 3.11+, formatted and linted with ruff; `ruff check .` and `ruff format --check .` must pass before a task is done.
- Naming: snake_case for functions and modules, PascalCase for classes and Pydantic models, UPPER_SNAKE for enums and constants.
- Type hints on every public function; state and tool payloads are Pydantic models or TypedDicts, never bare dicts in signatures.

### Structure
- Graph nodes return a dict update only; never mutate state or module-level globals inside a node.
- `raw_loop/` must not import langgraph or langchain (enforced by a test).
- Workers get tools only from the MCP client, filtered by an explicit allow-list per worker; no direct imports of mock backends in `agents/`.
- Write tools are reachable only through the executor node, never from a worker.
- Prompts live in one prompts module per agent, not inline in node code.

### Error handling & logging
- Classify every tool error as `transient` or `permanent`; only transient errors are retried (BR-04).
- Never swallow exceptions; log them with incident_id and node name, then either re-raise or convert them into a failed finding.
- Use the project logger; no `print()` outside `cli/`.

### Testing
- Every story's acceptance-criteria test name must exist and pass before the story is marked done.
- Every routing function has a test per branch.
- E2E tests use a stub approver; no test waits on real human input.
- Run `pytest -q` before declaring any task done.

### Dependencies
- Do not add a new package without asking first.
- No hosted-LLM SDKs (openai pointed at a non-local URL, anthropic, boto3 bedrock) — the Ollama base URL must be localhost.
- No real cloud SDK clients (boto3, snowflake-connector, fivetran).

### Never do
- Never commit secrets, keys or `.env` files.
- Never let a write tool execute without an approval record for gated tiers.
- Never hand-edit fixture files to make a failing test pass; fix the agent or the test.
- Never raise max_iterations or retry caps to make a test pass without logging the change in memory.md.

## Business rules
| ID | Rule | Example |
|---|---|---|
| BR-01 | Risk tiers: READ = auto-run; REVERSIBLE = one approval; DESTRUCTIVE = one approval with a before/after diff shown | get_job_status = READ; rerun_job = REVERSIBLE; alter_table, backfill_partition = DESTRUCTIVE |
| BR-02 | Agent loops stop at max_iterations = 6 and return an "incomplete" result rather than raising | Log Analyst hits 6 steps → returns partial finding with confidence 0 |
| BR-03 | A diagnosis with confidence below 0.6 routes to fallback escalation (needs confirmation) | Two workers disagree → confidence 0.4 → escalate |
| BR-04 | Transient tool errors are retried up to 3 attempts with exponential backoff and jitter; permanent errors are never retried | Timeout → retry; "table not found" → no retry |
| BR-05 | Malformed model tool calls are re-prompted at most 2 times per step, then the step fails | Invalid JSON twice, then a third failure → step failed |
| BR-06 | Verify may loop back to re-diagnose only once per incident; a second failure escalates | Fix applied, still failing twice → escalate |
| BR-07 | Each node has a token budget sized to the model's context window; logs are fetched in pages, never in full | Log page size 200 lines (needs confirmation after S3) |
| BR-08 | A pending approval expires after 24 hours and the incident escalates (needs confirmation) | Approval requested Mon 10:00 → expired Tue 10:00 |
| BR-09 | A rejected approval routes to fallback escalation, never to silent termination | Approver rejects alter_table → escalation summary produced |

## Git workflow
- Branch naming: `feature/S<id>-short-name` (e.g. `feature/S13-raw-react-loop`)
- Commit format: Conventional Commits with the story ID, e.g. `feat(raw-loop): add max_iterations guard [S14]`

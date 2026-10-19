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

## Gotchas & non-obvious behaviour
- Local 7–14B models produce malformed or partial tool-call JSON far more often than hosted models. Expect the model-level retry (BR-05) to fire regularly; track how often in performance.md.
- Jira CSV import: "Story Points" (company-managed) vs. "Story point estimate" (team-managed). Mapping the wrong field imports the points as blank without an error.
- At least one log fixture is deliberately bigger than the model context; that's the test for pagination and the sliding window, not a bug.

## Things that were tried and failed
- None yet.

## Environment / access notes
- No network egress beyond localhost is needed or allowed at runtime.
- Model choice is pending S3; until then, any prompt tuning is provisional.

## Stakeholder context
- Framing for client and account-lead audiences: faster MTTR on routine load failures, with a human still signing off on every write.
- The mentor/reviewer cares about verifiable syllabus coverage: TOPICS.md proofs, not demos.

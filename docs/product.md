# Product Requirements — Pipeline Incident Response Agent
_Last reviewed: 2026-10-19 · Owner: Fareed_

## Problem
When an ingestion load fails, whether a Fivetran sync, a Glue job or a warehouse load, an on-call engineer has to read long logs, check schemas and warehouse state across several tools, and then decide on a fix. Most of these failures are routine (schema drift, expired credentials, a suspended warehouse, late data, network blips), yet each one costs 30–90 minutes of triage and delays downstream reporting. Clients will not allow their logs, schemas or connection metadata to be sent to hosted AI services, so any automation must run inside their environment.

## Users
| Persona | Goal | Frequency of use |
|---|---|---|
| On-call data engineer | Get a root cause and a ready-to-approve fix without reading raw logs | Daily during on-call |
| Approver (client tech lead / platform owner) | Approve or reject write actions with clear evidence of what will change | Several times a week |
| Reviewer / mentor | Verify the system is safe, bounded and covers the syllabus | Once per milestone |

## Scope
### In scope (v1)
- User can trigger any of 5 mocked failure scenarios and receive a consolidated root-cause finding with a confidence score.
- User receives an ordered remediation plan in which every step is tagged with a risk tier.
- Read actions run automatically; write actions pause for human approval, and destructive actions show a diff first.
- An incident survives a process restart, including approvals left pending for hours.
- Transient tool failures and malformed model output are retried automatically, within fixed limits.
- A developer can rewind an incident to an earlier checkpoint and re-run it with a modified state.
- All tools are served via an MCP server and discovered at runtime.

### Explicitly out of scope
- Connections to real AWS, Snowflake, Fivetran or any client system.
- Hosted LLM APIs (OpenAI, Anthropic, Bedrock).
- A web UI or dashboard; v1 is CLI only.
- Slack, email or PagerDuty notifications.
- Auto-approval of any write action, even "safe" ones.
- Multi-tenant or multi-client separation.
- Alert ingestion from real monitoring tools (CloudWatch, Datadog); alerts come from the scenario injector.
- Fine-tuning or training models.

## Functional requirements
| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| FR-01 | Classify an incoming alert into a known type or UNKNOWN | Must | All 5 scenario alerts are classified correctly; a malformed alert yields UNKNOWN |
| FR-02 | Route each alert to only the relevant worker agents | Must | The routing table in architecture.md is satisfied for all 5 scenarios |
| FR-03 | Each worker returns a finding with root cause, evidence and confidence | Must | Finding validates against its schema; evidence cites log lines or query results |
| FR-04 | Supervisor consolidates findings into one diagnosis and flags conflicts | Must | test_supervisor_aggregates_three_workers passes |
| FR-05 | Low-confidence or unknown incidents go to a fallback escalation | Must | Confidence < BR-03 threshold routes to fallback; test passes |
| FR-06 | Planner produces an ordered, schema-valid remediation plan with risk tiers | Must | test_plan_has_ordered_steps_with_risk_tier passes |
| FR-07 | Write actions are gated by risk tier (BR-01) | Must | No audit-log write exists without an approver for gated tiers |
| FR-08 | Destructive actions show a before/after diff at approval | Must | test_destructive_action_requires_diff_approval passes |
| FR-09 | Incident state and pending approvals persist across restarts | Must | test_resume_after_process_restart passes; a pending approval is listed after restart |
| FR-10 | Transient tool errors are retried with backoff; permanent errors are not | Must | The transient-network scenario resolves without human input |
| FR-11 | Malformed model tool calls are re-prompted, within limits | Must | Retry count is visible in state; the step fails after BR-05's limit |
| FR-12 | Verify the fix: healthy → end; failing → re-diagnose once → escalate | Should | test_verify_failure_loops_back_once_then_escalates passes |
| FR-13 | Fork an incident from a past checkpoint with an edited state | Should | test_fork_from_checkpoint_changes_plan passes |
| FR-14 | Tools are discovered via MCP, not hard-coded | Should | test_mcp_tool_discovery passes |

## Non-functional requirements
- Performance: a full scenario run completes in under 5 minutes on the dev laptop with the chosen local model (excluding human approval wait time). (needs confirmation after S3)
- Security: no network egress except to localhost (Ollama, MCP). Mock data only; no real credentials anywhere in the repo.
- Bounded execution: every agent loop has max_iterations; every retry has a cap (see rules.md).
- Token discipline: no prompt exceeds the per-node budget in rules.md BR-07.
- Cost ceiling: zero external API spend.

## Success metrics
- 5 of 5 scenarios reach the correct root cause in end-to-end tests.
- 0 write actions in the audit log without a recorded approver for gated tiers.
- The transient-network scenario resolves with no human involvement.
- All 16 syllabus topics have a Proof entry in TOPICS.md.
- Median triage-to-plan time is recorded in docs/performance.md, as a baseline for the "minutes not hours" claim.

## Open questions
- Which local model? Decided by the S3 benchmark; record the result in memory.md.
- What confidence threshold should trigger fallback? 0.6 is a placeholder (BR-03).
- Should a rejected approval end the incident, or send it back to the planner for an alternative plan?
- How long should a pending approval stay valid before it expires (BR-08)?

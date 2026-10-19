# UI/UX Direction — Pipeline Incident Response Agent
<!-- v1 has no graphical UI. This file governs the CLI, which is the only interface —
     above all the approval prompt, where a bad layout leads to a bad approval. -->

## Design intent
An on-call engineer or approver, often mid-task and context-switching, reads the terminal. Within 10 seconds of an approval prompt they must be able to say what failed, what the system wants to do, what it will change, and how sure it is.

## Principles (ranked — when they conflict, higher wins)
1. Evidence before action — every approval prompt shows the root cause, its evidence and the confidence before the action.
2. Safe defaults — the default answer to any approval prompt is reject; Enter alone never approves.
3. Scannable over complete — a summary first; full logs and state only on request (`--verbose`, `show`).
4. Consistency — every incident uses the same section order and the same status labels.

## Visual system
- Component library: Rich (if approved as a dependency in S1); otherwise plain text with ASCII separators.
- Status labels are text plus colour, never colour alone: `[OK]`, `[PENDING]`, `[FAILED]`, `[ESCALATED]`.
- Risk tiers: `READ`, `REVERSIBLE`, `DESTRUCTIVE`, printed in caps; DESTRUCTIVE is always followed by a diff block.
- Output must be readable in an 80-column terminal and with colour disabled (`NO_COLOR=1`).

## Layout & navigation
Commands (see CLAUDE.md): `run`, `approvals`, `show <incident>`, `checkpoints <incident>`, `fork <incident> <checkpoint>`.

Every incident view prints these sections in this order:
1. Incident header: ID, alert type, status.
2. Diagnosis: root cause, confidence, conflicts (if any).
3. Evidence: at most 5 lines, with a pointer to the full logs.
4. Plan: numbered steps with their risk tiers.
5. Pending action, if any: tool, args, diff, and the prompt `[a]pprove / [r]eject / [e]dit (default: reject)`.

## Screen inventory
| Screen | Purpose | Status |
|---|---|---|
| `run` output | Live progress of nodes and a final summary | planned |
| `approvals` list | All pending approvals across incidents, oldest first, with age | planned |
| Approval prompt | Decide on one gated action | planned |
| `show` incident | Full incident view in the section order above | planned |
| `checkpoints` / `fork` | Time-travel debugging | planned |

## Patterns to reuse
- Lists: oldest first, with an age column (e.g. "3h 12m").
- Edits: `[e]dit` opens the args as JSON, validates them against the tool schema, and re-shows the diff before asking again.
- Loading, empty and error states: every command prints a one-line state message (e.g. "No pending approvals."), never empty output.

## Accessibility
- No colour-only meaning; works with NO_COLOR.
- No spinners that overwrite lines when output is not a TTY (CI logs stay readable).

## Do not
- No auto-approve flags in v1 (a test stub is the only exception, and only inside tests/).
- No full log dumps by default.
- No emoji as status indicators.

## References
- Terraform `plan` / `apply` — a diff before a destructive change, with explicit confirmation.

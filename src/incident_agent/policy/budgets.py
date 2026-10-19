"""Per-node prompt token budgets (BR-07).

Sized for an 8k-context local model, leaving room for the reply. Revisit after the S3 model
decision (needs confirmation, rules.md BR-07).
"""

from __future__ import annotations

MODEL_CONTEXT_TOKENS = 8192

NODE_BUDGETS: dict[str, int] = {
    "triage": 1500,
    "log_analyst": 6000,
    "planner": 4000,
}


def budget_for(node: str) -> int:
    return NODE_BUDGETS[node]

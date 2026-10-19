"""Risk-tier policy (BR-01): READ auto-runs; REVERSIBLE needs one approval;
DESTRUCTIVE needs one approval with a before/after diff shown."""

from __future__ import annotations

from incident_agent.models import PlanStep, RiskTier

_ORDER = {RiskTier.READ: 0, RiskTier.REVERSIBLE: 1, RiskTier.DESTRUCTIVE: 2}


def requires_approval(tier: str | RiskTier) -> bool:
    return RiskTier(tier) is not RiskTier.READ


def requires_diff(tier: str | RiskTier) -> bool:
    return RiskTier(tier) is RiskTier.DESTRUCTIVE


def stricter(a: str | RiskTier, b: str | RiskTier) -> RiskTier:
    """The more restrictive of two tiers (used so a plan can never downgrade a tool)."""
    a, b = RiskTier(a), RiskTier(b)
    return a if _ORDER[a] >= _ORDER[b] else b


def gated_steps(plan: list[PlanStep]) -> list[PlanStep]:
    return [s for s in plan if requires_approval(s["risk_tier"])]

"""Supervisor aggregation (S26): merge worker findings into one diagnosis (FR-04).

Rules:
- Only findings from the current diagnosis round count.
- Each issue category scores the sum of its findings' confidences; the top score wins.
- confidence = mean confidence of the winning findings x (winning score / all issue scores).
  Two workers disagreeing at 0.8 each therefore yields 0.4 (BR-03 example).
- A worker that looked in its own area and found NO_ISSUE contradicts a winner in that area:
  it is recorded as a conflict and halves the confidence.
- Conflicts are always listed in diagnosis.conflicts, never dropped.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from langchain_core.messages import AIMessage

from incident_agent.graph.routing import SCHEMA_INSPECTOR, WAREHOUSE_AGENT
from incident_agent.graph.state import IncidentState, current_findings
from incident_agent.models import NO_ISSUE, AlertType, Diagnosis, Finding

NODE = "aggregate"

# Categories each specialist is authoritative about.
WORKER_AREAS: dict[str, frozenset[str]] = {
    SCHEMA_INSPECTOR: frozenset({AlertType.SCHEMA_DRIFT.value}),
    WAREHOUSE_AGENT: frozenset({AlertType.WAREHOUSE_UNAVAILABLE.value, AlertType.LATE_DATA.value}),
}


def aggregate_findings(findings: list[Finding]) -> Diagnosis:
    usable = [f for f in findings if f["status"] == "complete"]
    issues = [f for f in usable if f["category"] not in (NO_ISSUE, AlertType.UNKNOWN.value)]
    workers = sorted({f["worker"] for f in findings})
    if not issues:
        return {
            "category": AlertType.UNKNOWN.value,
            "root_cause": "No worker identified a root cause",
            "confidence": 0.0,
            "conflicts": [
                f"{f['worker']}: {f['status']} - {f['root_cause']}"
                for f in findings
                if f["status"] != "complete"
            ],
            "evidence": [e for f in findings for e in f["evidence"]][:8],
            "workers": workers,
        }

    scores: dict[str, float] = defaultdict(float)
    for f in issues:
        scores[f["category"]] += f["confidence"]
    winner = max(scores, key=lambda c: (scores[c], c))
    winners = [f for f in issues if f["category"] == winner]
    total = sum(scores.values())
    confidence = (sum(f["confidence"] for f in winners) / len(winners)) * (scores[winner] / total)

    conflicts = [
        f"{f['worker']} reports {f['category']} ({f['confidence']:.2f}): {f['root_cause']}"
        for f in issues
        if f["category"] != winner
    ]
    for f in usable:
        if f["category"] == NO_ISSUE and winner in WORKER_AREAS.get(f["worker"], ()):
            conflicts.append(f"{f['worker']} found no issue in its area: {f['root_cause']}")
            confidence *= 0.5

    best = max(winners, key=lambda f: f["confidence"])
    evidence = list(best["evidence"]) + [e for f in winners if f is not best for e in f["evidence"]]
    return {
        "category": winner,
        "root_cause": best["root_cause"],
        "confidence": round(confidence, 3),
        "conflicts": conflicts,
        "evidence": evidence[:8],
        "workers": workers,
    }


def aggregate(state: IncidentState) -> dict[str, Any]:
    diagnosis = aggregate_findings(current_findings(state))
    note = f"aggregate: {diagnosis['category']} confidence {diagnosis['confidence']:.2f}"
    if diagnosis["conflicts"]:
        note += f" ({len(diagnosis['conflicts'])} conflict(s))"
    return {
        "diagnosis": diagnosis,
        "messages": [AIMessage(content=note, name=NODE)],
        "node_log": [NODE],
    }

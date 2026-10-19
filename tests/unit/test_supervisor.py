"""Supervisor aggregation (S26)."""

from __future__ import annotations

from incident_agent.graph.nodes.aggregate import aggregate, aggregate_findings


def _f(worker, category, confidence=0.8, status="complete", rnd=1, evidence=None):
    return {
        "worker": worker,
        "category": category,
        "root_cause": f"{worker} thinks {category}",
        "evidence": evidence or [f"{worker} evidence"],
        "confidence": confidence,
        "status": status,
        "round": rnd,
    }


def test_supervisor_aggregates_three_workers():
    findings = [
        _f("log_analyst", "WAREHOUSE_UNAVAILABLE", 0.85, evidence=["L702: LOAD_WH suspended"]),
        _f("warehouse_agent", "WAREHOUSE_UNAVAILABLE", 0.9, evidence=["LOAD_WH state=SUSPENDED"]),
        _f("schema_inspector", "SCHEMA_DRIFT", 0.6),
    ]
    d = aggregate_findings(findings)
    assert d["category"] == "WAREHOUSE_UNAVAILABLE"
    assert d["workers"] == ["log_analyst", "schema_inspector", "warehouse_agent"]
    assert d["root_cause"] == "warehouse_agent thinks WAREHOUSE_UNAVAILABLE"
    assert "L702: LOAD_WH suspended" in d["evidence"]
    # The dissenting worker is kept as a conflict, and it lowers the confidence.
    assert any("schema_inspector reports SCHEMA_DRIFT" in c for c in d["conflicts"])
    assert 0 < d["confidence"] < 0.875


def test_agreement_keeps_confidence():
    d = aggregate_findings(
        [_f("log_analyst", "LATE_DATA", 0.8), _f("warehouse_agent", "LATE_DATA", 0.9)]
    )
    assert d["category"] == "LATE_DATA" and d["conflicts"] == []
    assert abs(d["confidence"] - 0.85) < 1e-9


def test_two_workers_disagreeing_yields_low_confidence():
    d = aggregate_findings(
        [_f("log_analyst", "AUTH_FAILURE", 0.8), _f("warehouse_agent", "LATE_DATA", 0.8)]
    )
    assert d["confidence"] == 0.4  # BR-03 example: escalates at threshold 0.6
    assert len(d["conflicts"]) == 1


def test_specialist_no_issue_in_its_area_is_a_conflict():
    d = aggregate_findings(
        [_f("log_analyst", "SCHEMA_DRIFT", 0.85), _f("schema_inspector", "NO_ISSUE", 0.8)]
    )
    assert d["category"] == "SCHEMA_DRIFT"
    assert any("schema_inspector found no issue" in c for c in d["conflicts"])
    assert d["confidence"] < 0.6


def test_no_issue_outside_area_is_not_a_conflict():
    d = aggregate_findings(
        [_f("log_analyst", "AUTH_FAILURE", 0.85), _f("warehouse_agent", "NO_ISSUE", 0.7)]
    )
    assert d["conflicts"] == [] and d["confidence"] == 0.85


def test_failed_workers_only_gives_unknown():
    d = aggregate_findings([_f("log_analyst", "UNKNOWN", 0.0, status="incomplete")])
    assert d["category"] == "UNKNOWN" and d["confidence"] == 0.0
    assert d["conflicts"]


def test_aggregate_node_uses_current_round_only():
    state = {
        "diagnosis_round": 2,
        "findings": [
            _f("log_analyst", "AUTH_FAILURE", 0.9, rnd=1),
            _f("log_analyst", "LATE_DATA", 0.7, rnd=2),
        ],
    }
    out = aggregate(state)
    assert out["diagnosis"]["category"] == "LATE_DATA"
    assert out["node_log"] == ["aggregate"]

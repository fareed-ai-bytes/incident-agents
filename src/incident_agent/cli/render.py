"""Plain-text rendering for the CLI (design.md).

Readable in 80 columns with colour disabled: status is always a text label, never colour
alone. Every incident view prints the same sections in the same order.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from typing import Any

WIDTH = 80
RULE = "-" * WIDTH
MAX_EVIDENCE = 5

_LABELS = {
    "RESOLVED": "[OK]",
    "EXECUTED": "[OK]",
    "ESCALATED": "[ESCALATED]",
    "FAILED": "[FAILED]",
}


def status_label(status: str) -> str:
    return _LABELS.get(status, "[PENDING]")


def wrap(text: str, indent: str = "  ") -> str:
    return "\n".join(
        textwrap.fill(line, WIDTH, initial_indent=indent, subsequent_indent=indent + "  ")
        for line in str(text).splitlines() or [""]
    )


def section(title: str) -> str:
    return f"\n{title}\n{'-' * len(title)}"


def render_incident(values: dict[str, Any], verbose: bool = False) -> str:
    """Header, Diagnosis, Evidence, Plan, Pending action, then outcome."""
    alert = values.get("alert") or {}
    status = values.get("status", "")
    out = [
        RULE,
        f"Incident {values.get('incident_id')}  {status_label(status)} {status}",
        f"Alert type: {values.get('alert_type') or 'UNKNOWN'}   Pipeline: {alert.get('pipeline', '?')}",
        RULE,
    ]

    out.append(section("Diagnosis"))
    diag = values.get("diagnosis")
    if diag:
        out.append(wrap(f"Root cause: {diag['root_cause']}"))
        out.append(wrap(f"Category: {diag['category']}   Confidence: {diag['confidence']:.2f}"))
        for c in diag.get("conflicts", []):
            out.append(wrap(f"Conflict: {c}"))
    else:
        out.append("  No diagnosis yet.")

    out.append(section("Evidence"))
    evidence = (diag or {}).get("evidence", [])
    shown = evidence if verbose else evidence[:MAX_EVIDENCE]
    out.extend(wrap(e) for e in shown) if shown else out.append("  No evidence recorded.")
    if len(evidence) > len(shown):
        out.append(f"  ... {len(evidence) - len(shown)} more (use --verbose)")
    if alert.get("pipeline"):
        out.append(wrap(f"Full logs: search_logs / fetch_log_window on {alert['pipeline']}"))

    out.append(section("Plan"))
    plan = values.get("plan") or []
    results = {r["index"]: r["status"] for r in values.get("step_results") or []}
    if plan:
        for step in plan:
            done = f"  -> {results[step['index']]}" if step["index"] in results else ""
            out.append(wrap(f"{step['index'] + 1}. {step['tool']} [{step['risk_tier']}]{done}"))
            if verbose and step.get("rationale"):
                out.append(wrap(step["rationale"], "       "))
    else:
        out.append("  No plan.")

    pending = values.get("pending_approval")
    if pending:
        out.append(section("Pending action"))
        for item in pending["items"]:
            out.append(render_item(item))

    escalation = values.get("escalation")
    if escalation:
        out.append(section("Escalation"))
        out.append(wrap(escalation["summary"]))
    elif status == "RESOLVED":
        out.append(section("Outcome"))
        out.append(
            f"  [OK] Pipeline healthy after {values.get('verify_attempts', 0)} verification(s)."
        )
    if verbose:
        out.append(section("Counters"))
        out.append(wrap(f"retries: {values.get('retry_counts') or {}}"))
        out.append(wrap(f"re-prompts: {values.get('reprompt_counts') or {}}"))
        out.append(wrap(f"prompt tokens: {values.get('token_usage') or {}}"))
        out.append(wrap(f"nodes: {' > '.join(values.get('node_log') or [])}"))
    return "\n".join(out)


def render_item(item: dict[str, Any], diff: list[str] | None = None) -> str:
    """One gated step. DESTRUCTIVE steps are always followed by a diff block (design.md)."""
    lines = [
        f"  Step {item['step_index'] + 1}: {item['tool']} [{item['risk_tier']}]",
        wrap(f"Args: {json.dumps(item['args'], sort_keys=True)}", "    "),
    ]
    if item.get("rationale"):
        lines.append(wrap(f"Why: {item['rationale']}", "    "))
    if diff is not None:
        lines.append("    Diff:")
        lines.extend(_block(diff))
    elif item.get("before") or item.get("after"):
        lines.append("    Before:")
        lines.extend(_block(item.get("before", [])))
        lines.append("    After:")
        lines.extend(_block(item.get("after", [])))
    return "\n".join(lines)


def _block(lines: list[str], indent: str = "      ") -> list[str]:
    """Indent preview/diff lines, wrapping any that would pass 80 columns."""
    out = []
    for ln in lines:
        if len(indent) + len(ln) <= WIDTH:
            out.append(indent + ln)
        else:
            out.extend(
                textwrap.wrap(ln, WIDTH, initial_indent=indent, subsequent_indent=indent + "    ")
            )
    return out


def age(since_iso: str, now: datetime) -> str:
    delta = now - datetime.fromisoformat(since_iso)
    minutes = max(0, int(delta.total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


PROMPT = "[a]pprove / [r]eject / [e]dit (default: reject): "


def parse_choice(answer: str | None) -> str:
    """'a'/'approve' -> approve, 'e'/'edit' -> edit; anything else, Enter included -> reject."""
    a = (answer or "").strip().lower()
    if a in ("a", "approve"):
        return "approve"
    if a in ("e", "edit"):
        return "edit"
    return "reject"

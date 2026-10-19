"""Command-line interface: `python -m incident_agent.cli <command>`.

Commands: seed, inject, run, approvals, show, checkpoints, fork, resume. Every command prints a one-line state
message, never empty output (design.md).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace

from incident_agent.cli.render import (
    PROMPT,
    age,
    parse_choice,
    render_incident,
    render_item,
    status_label,
    wrap,
)
from incident_agent.config import ConfigError, Settings
from incident_agent.graph.hitl import APPROVED, REJECTED, ApprovalSession, DecisionError
from incident_agent.graph.runner import ForkError, IncidentNotFoundError, IncidentRunner
from incident_agent.graph.runtime import utcnow
from incident_agent.llm.base import ModelError
from incident_agent.log import configure_logging
from incident_agent.mocks.injector import inject
from incident_agent.mocks.scenarios import SCENARIOS, UnknownScenarioError
from incident_agent.mocks.seed import seed_all
from incident_agent.policy.approvals import expired

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

Ask = Callable[[str], str]
Say = Callable[[str], None]


# -- helpers ----------------------------------------------------------------------------------


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""  # closed stdin counts as Enter: reject


def _say(text: str) -> None:
    print(text)


def default_approver() -> str:
    return os.environ.get("INCIDENT_APPROVER") or getpass.getuser()


def open_runner(settings: Settings, model: str | None) -> IncidentRunner:
    if model:
        settings = replace(settings, model_provider=model)
    if not settings.warehouse_db.exists():
        raise ConfigError(
            f"mock warehouse not found at {settings.warehouse_db}; run: python -m incident_agent.cli seed"
        )
    return IncidentRunner(settings)


def interactive(args: argparse.Namespace) -> bool:
    return not args.no_input and sys.stdin.isatty()


def approve_interactively(
    runner: IncidentRunner, incident_id: str, approver: str, ask: Ask = _ask, say: Say = _say
) -> dict:
    """Walk the approver through each gated step. Enter alone rejects."""
    session = ApprovalSession(runner, incident_id, approver)
    say(render_incident(session.values))
    for idx in sorted(session.items):
        while True:
            item = session.item(idx)
            diff = session.render_diff(idx) if item["risk_tier"] == "DESTRUCTIVE" else None
            say("\n" + render_item(item, diff))
            choice = parse_choice(ask(PROMPT))
            if choice == "approve":
                session.decide(idx, APPROVED)
                say("  Approved.")
                break
            if choice == "reject":
                session.decide(idx, REJECTED)
                say("  Rejected.")
                break
            raw = ask("  New args as JSON: ")
            try:
                session.edit(idx, json.loads(raw))
            except ValueError as exc:  # JSONDecodeError and DecisionError
                say(f"  [FAILED] {exc}")
            # Loop: re-show the (possibly updated) diff and ask again.
    final = session.submit()
    say("\n" + render_incident(final))
    return final


# -- commands ---------------------------------------------------------------------------------


def cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    counts = seed_all(settings)
    print(f"[OK] Seeded mock warehouse at {settings.warehouse_db}")
    for table, n in counts.items():
        print(f"  {table:<18} {n:>5} rows")
    print(f"[OK] Audit DB ready at {settings.audit_db}")
    return EXIT_OK


def cmd_inject(args: argparse.Namespace, settings: Settings) -> int:
    try:
        incident_id, alert = inject(args.scenario)
    except UnknownScenarioError as exc:
        print(f"[FAILED] {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"[OK] Injected {args.scenario} as {incident_id}")
    print(json.dumps(alert, indent=2))
    return EXIT_OK


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    if args.scenario not in SCENARIOS:
        print(f"[FAILED] {UnknownScenarioError(args.scenario)}", file=sys.stderr)
        return EXIT_USAGE
    with open_runner(settings, args.model) as runner:
        print(f"Running {args.scenario} with model {runner.model.name} ...")
        incident_id = runner.start(args.scenario)
        values = runner.snapshot(incident_id).values
        print(wrap(f"Nodes: {' > '.join(values.get('node_log', []))}", ""))
        if values.get("pending_approval") and interactive(args):
            approve_interactively(runner, incident_id, args.approver or default_approver())
            return EXIT_OK
        print(render_incident(values, verbose=args.verbose))
        if values.get("pending_approval"):
            print(
                f"\n{status_label('PENDING_APPROVAL')} Waiting for approval. Run: python -m incident_agent.cli approvals"
            )
    return EXIT_OK


def cmd_approvals(args: argparse.Namespace, settings: Settings) -> int:
    with open_runner(settings, args.model) as runner:
        now = utcnow()
        rows = []
        for incident_id in runner.pending_incidents():
            pending = runner.snapshot(incident_id).values["pending_approval"]
            rows.append((pending["requested_at"], incident_id, pending))
        rows.sort()  # oldest first
        if args.incident:
            rows = [r for r in rows if r[1] == args.incident]
        if not rows:
            print("No pending approvals.")
            return EXIT_OK
        print(f"{'Incident':<46} {'Steps':>5}  {'Age':>8}")
        for requested_at, incident_id, pending in rows:
            late = "  EXPIRED" if expired(requested_at, now, settings.approval_ttl_hours) else ""
            print(
                f"{incident_id:<46} {len(pending['items']):>5}  {age(requested_at, now):>8}{late}"
            )
        if not interactive(args):
            print("\nRe-run in a terminal to decide (Enter alone rejects).")
            return EXIT_OK
        approver = args.approver or default_approver()
        for _, incident_id, _ in rows:
            approve_interactively(runner, incident_id, approver)
    return EXIT_OK


def cmd_show(args: argparse.Namespace, settings: Settings) -> int:
    with open_runner(settings, args.model) as runner:
        print(render_incident(runner.snapshot(args.incident).values, verbose=args.verbose))
    return EXIT_OK


def cmd_resume(args: argparse.Namespace, settings: Settings) -> int:
    with open_runner(settings, args.model) as runner:
        snap = runner.snapshot(args.incident)
        if not snap.next:
            print(f"Incident {args.incident} already finished: {snap.values.get('status')}")
            return EXIT_OK
        if tuple(snap.next) == ("execute",):
            print("Incident is waiting for approval. Run: python -m incident_agent.cli approvals")
            return EXIT_OK
        values = runner.resume(args.incident)
        print(render_incident(values, verbose=args.verbose))
    return EXIT_OK


def cmd_checkpoints(args: argparse.Namespace, settings: Settings) -> int:
    with open_runner(settings, args.model) as runner:
        infos = runner.checkpoints(args.incident)
        print(f"{len(infos)} checkpoints for {args.incident} (oldest first)")
        print(f"{'#':>3}  {'checkpoint':<36}  {'step':>4}  {'next':<18} {'status':<16}")
        for i, c in enumerate(infos):
            nxt = ",".join(c.next) or "(end)"
            print(f"{i:>3}  {c.checkpoint_id:<36}  {c.step:>4}  {nxt[:18]:<18} {c.status[:16]:<16}")
        print(
            "\nFork with: python -m incident_agent.cli fork <incident> <#|checkpoint> --category ..."
        )
    return EXIT_OK


def cmd_fork(args: argparse.Namespace, settings: Settings) -> int:
    with open_runner(settings, args.model) as runner:
        checkpoint_id = runner.resolve_checkpoint(args.incident, args.checkpoint)
        values = runner.graph.get_state(
            {"configurable": {"thread_id": args.incident, "checkpoint_id": checkpoint_id}}
        ).values
        edits: dict = {}
        if any(v is not None for v in (args.category, args.root_cause, args.confidence)):
            diag = dict(values.get("diagnosis") or {})
            if not diag:
                print("[FAILED] that checkpoint has no diagnosis to edit", file=sys.stderr)
                return EXIT_USAGE
            if args.category:
                diag["category"] = args.category.upper()
            if args.root_cause:
                diag["root_cause"] = args.root_cause
            if args.confidence is not None:
                diag["confidence"] = args.confidence
            edits["diagnosis"] = diag
        new_id = runner.fork(args.incident, checkpoint_id, edits)
        print(f"[OK] Forked {args.incident} at {checkpoint_id} into {new_id}")
        print(render_incident(runner.snapshot(new_id).values, verbose=args.verbose))
    return EXIT_OK


# -- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incident-agent", description="Pipeline incident response agent (local only)."
    )
    parser.add_argument("--debug", action="store_true", help="show debug logs on stderr")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func: Callable, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        return p

    def runner_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", choices=["ollama", "heuristic"], help="override MODEL_PROVIDER")
        p.add_argument("--verbose", action="store_true", help="full evidence, rationale, counters")

    def approval_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--approver", help="your name for the audit log (default: $INCIDENT_APPROVER or login)"
        )
        p.add_argument("--no-input", action="store_true", help="never prompt; just report")

    add("seed", cmd_seed, "seed the mock warehouse and audit DB")
    p = add("inject", cmd_inject, "emit the alert for a mocked failure scenario")
    p.add_argument("--scenario", required=True, help=f"one of: {', '.join(SCENARIOS)}")

    p = add("run", cmd_run, "run a scenario through the agent")
    p.add_argument("--scenario", required=True, help=f"one of: {', '.join(SCENARIOS)}")
    runner_opts(p)
    approval_opts(p)

    p = add("approvals", cmd_approvals, "list and decide pending approvals, oldest first")
    p.add_argument("--incident", help="only this incident")
    runner_opts(p)
    approval_opts(p)

    p = add("show", cmd_show, "show one incident")
    p.add_argument("incident")
    runner_opts(p)

    p = add("checkpoints", cmd_checkpoints, "list an incident's checkpoints (time travel)")
    p.add_argument("incident")
    runner_opts(p)

    p = add("fork", cmd_fork, "re-run an incident from a past checkpoint with edited state")
    p.add_argument("incident")
    p.add_argument("checkpoint", help="checkpoint id, unique prefix, or # from `checkpoints`")
    p.add_argument("--category", help="edited diagnosis category (e.g. WAREHOUSE_UNAVAILABLE)")
    p.add_argument("--root-cause", help="edited diagnosis root cause")
    p.add_argument("--confidence", type=float, help="edited diagnosis confidence")
    runner_opts(p)

    p = add("resume", cmd_resume, "resume an incident interrupted by a crash")
    p.add_argument("incident")
    runner_opts(p)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging("DEBUG" if args.debug else None)
    try:
        settings = Settings.from_env()
        return args.func(args, settings)
    except (ConfigError, IncidentNotFoundError, DecisionError, ForkError, ModelError) as exc:
        print(f"[FAILED] {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

"""Command-line interface: `python -m incident_agent.cli <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from incident_agent.config import Settings
from incident_agent.log import configure_logging
from incident_agent.mocks.injector import inject
from incident_agent.mocks.scenarios import SCENARIOS, UnknownScenarioError
from incident_agent.mocks.seed import seed_all

EXIT_OK = 0
EXIT_USAGE = 2


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incident-agent", description="Pipeline incident response agent (local only)."
    )
    parser.add_argument("--verbose", action="store_true", help="show debug logs on stderr")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("seed", help="seed the mock warehouse and audit DB")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("inject", help="emit the alert for a mocked failure scenario")
    p.add_argument("--scenario", required=True, help=f"one of: {', '.join(SCENARIOS)}")
    p.set_defaults(func=cmd_inject)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging("DEBUG" if args.verbose else None)
    settings = Settings.from_env()
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())

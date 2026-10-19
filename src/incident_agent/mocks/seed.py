"""Seed every mock backend: `python -m incident_agent.mocks.seed`."""

from __future__ import annotations

from incident_agent.config import Settings
from incident_agent.log import configure_logging, get_logger
from incident_agent.mocks import warehouse
from incident_agent.mocks.job_runner import FakeJobRunner

log = get_logger(__name__)


def seed_all(settings: Settings) -> dict[str, int]:
    counts = warehouse.seed(settings.warehouse_db)
    FakeJobRunner(settings.audit_db)  # creates the audit schema
    return counts


def main() -> None:
    configure_logging("INFO")
    settings = Settings.from_env()
    counts = seed_all(settings)
    log.info("seeded %s: %s", settings.warehouse_db, counts)
    log.info("audit DB ready at %s", settings.audit_db)


if __name__ == "__main__":
    main()

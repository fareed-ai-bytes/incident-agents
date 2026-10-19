"""The five mocked failure scenarios: one pipeline each, with its alert and expected outcome."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class Scenario:
    id: str
    pipeline: str
    expected_alert_type: str
    alert_summary: str
    alert_message: str
    warehouse: str
    log_lines: int
    # Line number (1-based) of the root-cause signal in the generated log.
    root_cause_line: int
    root_cause_text: str
    # Write actions that must have succeeded for the pipeline to be healthy again.
    required_fixes: frozenset[str] = field(default_factory=frozenset)
    # How many times read tools on this pipeline fail transiently before succeeding.
    transient_failures: int = 0
    table: str = ""
    partition: str = ""

    @property
    def fixture_dir(self) -> Path:
        return FIXTURES_DIR / self.id

    @property
    def log_path(self) -> Path:
        return self.fixture_dir / "pipeline.log"


SCENARIOS: dict[str, Scenario] = {
    s.id: s
    for s in (
        Scenario(
            id="schema_drift",
            pipeline="crm_customers_sync",
            expected_alert_type="SCHEMA_DRIFT",
            alert_summary="Load failed for crm_customers_sync",
            alert_message="COPY INTO RAW.CRM_CUSTOMERS failed: invalid identifier 'LOYALTY_TIER'",
            warehouse="TRANSFORM_WH",
            log_lines=1200,
            root_cause_line=874,
            root_cause_text=(
                'ERROR [loader] COPY INTO RAW.CRM_CUSTOMERS failed: column "loyalty_tier" '
                "not found in target table (source schema added loyalty_tier VARCHAR)"
            ),
            required_fixes=frozenset({"alter_table", "rerun_job"}),
            table="crm_customers",
        ),
        Scenario(
            id="auth_failure",
            pipeline="payments_fivetran_sync",
            expected_alert_type="AUTH_FAILURE",
            alert_summary="Connector sync failed for payments_fivetran_sync",
            alert_message="Connector sync failed: authentication error for service user",
            warehouse="TRANSFORM_WH",
            log_lines=900,
            root_cause_line=611,
            root_cause_text=(
                "ERROR [connector] authentication failed for user SVC_FIVETRAN: "
                "password expired (code 390106)"
            ),
            required_fixes=frozenset({"rotate_credentials", "rerun_job"}),
            table="payments",
        ),
        Scenario(
            id="warehouse_unavailable",
            pipeline="orders_warehouse_load",
            expected_alert_type="WAREHOUSE_UNAVAILABLE",
            alert_summary="Warehouse load failed for orders_warehouse_load",
            alert_message="Load failed: warehouse LOAD_WH is suspended",
            warehouse="LOAD_WH",
            log_lines=1000,
            root_cause_line=702,
            root_cause_text=(
                "ERROR [warehouse] Warehouse LOAD_WH is suspended and auto_resume is disabled "
                "(code 000606)"
            ),
            required_fixes=frozenset({"resume_warehouse", "rerun_job"}),
            table="orders",
        ),
        Scenario(
            id="late_data",
            pipeline="events_daily_partition",
            expected_alert_type="LATE_DATA",
            alert_summary="Freshness check failed for events_daily_partition",
            alert_message="Freshness check failed: partition dt=2026-10-18 missing for events_daily",
            warehouse="TRANSFORM_WH",
            # Deliberately far larger than any node's token budget (BR-07, memory.md).
            log_lines=6000,
            root_cause_line=4321,
            root_cause_text=(
                "ERROR [loader] expected partition dt=2026-10-18 missing in "
                "s3://mock-bucket/events/ (late upstream delivery)"
            ),
            required_fixes=frozenset({"backfill_partition"}),
            table="events_daily",
            partition="dt=2026-10-18",
        ),
        Scenario(
            id="transient_network",
            pipeline="inventory_glue_job",
            expected_alert_type="TRANSIENT_NETWORK",
            alert_summary="Job failed for inventory_glue_job",
            alert_message="Job attempt failed: connection reset by peer (inventory-api)",
            warehouse="TRANSFORM_WH",
            log_lines=800,
            root_cause_line=455,
            root_cause_text=(
                "ERROR [http] ConnectionResetError: connection reset by peer while reading "
                "from inventory-api (attempt 1/3)"
            ),
            required_fixes=frozenset(),
            transient_failures=2,
            table="inventory",
        ),
    )
}

PIPELINES: dict[str, Scenario] = {s.pipeline: s for s in SCENARIOS.values()}


class UnknownScenarioError(KeyError):
    def __str__(self) -> str:
        return f"unknown scenario {self.args[0]!r}; choose one of: {', '.join(SCENARIOS)}"


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError:
        raise UnknownScenarioError(scenario_id) from None


def scenario_for_pipeline(pipeline: str) -> Scenario:
    try:
        return PIPELINES[pipeline]
    except KeyError:
        raise UnknownScenarioError(pipeline) from None

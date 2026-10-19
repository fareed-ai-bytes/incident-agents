import pytest

from incident_agent.mocks import warehouse


def test_warehouse_seed_creates_business_tables_and_load_audit(settings):
    counts = warehouse.seed(settings.warehouse_db)
    for table in (*warehouse.BUSINESS_TABLES, "load_audit", "warehouse_status", "partitions"):
        assert counts[table] > 0, table
    assert len(warehouse.BUSINESS_TABLES) >= 3


def test_warehouse_seed_is_idempotent(settings):
    first = warehouse.seed(settings.warehouse_db)
    second = warehouse.seed(settings.warehouse_db)
    assert first == second == warehouse.row_counts(settings.warehouse_db)


def test_warehouse_queries(settings):
    warehouse.seed(settings.warehouse_db)
    cols = [c["name"] for c in warehouse.table_schema(settings.warehouse_db, "crm_customers")]
    assert "loyalty_tier" not in cols
    audit = warehouse.load_audit(settings.warehouse_db, "orders_warehouse_load")
    assert audit[0]["status"] == "FAILED"
    assert warehouse.warehouse_status(settings.warehouse_db, "LOAD_WH")["state"] == "SUSPENDED"
    assert (
        warehouse.partition_arrived(settings.warehouse_db, "events_daily", "dt=2026-10-18") is False
    )
    assert (
        warehouse.partition_arrived(settings.warehouse_db, "events_daily", "dt=2026-10-17") is True
    )


def test_warehouse_missing_file_fails_fast(settings):
    with pytest.raises(warehouse.WarehouseError, match="seed"):
        warehouse.table_schema(settings.warehouse_db, "orders")


def test_warehouse_unknown_table_is_lookup_error(settings):
    warehouse.seed(settings.warehouse_db)
    with pytest.raises(LookupError):
        warehouse.table_schema(settings.warehouse_db, "nope")

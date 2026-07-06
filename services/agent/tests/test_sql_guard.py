"""Unit tests for the SQL guard — run with: pytest services/agent/tests"""
import pytest

from validators.sql_guard import SqlGuardError, guard_sql


def test_simple_select_gets_limit():
    out = guard_sql("SELECT district, SUM(visits) v FROM utilization_daily u JOIN facilities f ON u.facility_id = f.facility_id GROUP BY district")
    assert "LIMIT 200" in out


def test_existing_limit_preserved():
    out = guard_sql("SELECT * FROM facilities LIMIT 5")
    assert "LIMIT 5" in out and "200" not in out


def test_cte_allowed():
    out = guard_sql(
        "WITH recent AS (SELECT * FROM utilization_daily WHERE date > '2026-01-01') "
        "SELECT district FROM facilities WHERE facility_id IN (SELECT facility_id FROM recent)"
    )
    assert out


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM facilities WHERE 1=1",
        "INSERT INTO facilities (facility_id) VALUES ('x')",
        "UPDATE facilities SET name = 'x'",
        "DROP TABLE facilities",
        "CREATE TABLE t AS SELECT 1",
        "MERGE facilities t USING facilities s ON FALSE WHEN NOT MATCHED THEN INSERT ROW",
    ],
)
def test_writes_rejected(sql):
    with pytest.raises(SqlGuardError):
        guard_sql(sql)


def test_multiple_statements_rejected():
    with pytest.raises(SqlGuardError):
        guard_sql("SELECT 1; SELECT 2")


def test_unknown_table_rejected():
    with pytest.raises(SqlGuardError, match="not allowed"):
        guard_sql("SELECT * FROM secrets")


def test_injection_string_rejected():
    with pytest.raises(SqlGuardError):
        guard_sql("SELECT * FROM facilities; DROP TABLE facilities")

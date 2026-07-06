"""SQL guard: the only path between the LLM and BigQuery.

Rejects anything that is not a single SELECT over allowlisted tables and
injects a row LIMIT. Executed *before* every query; the worker-side billing
cap (maximum_bytes_billed) is applied separately in tools/bigquery.py.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {
    "facilities",
    "utilization_daily",
    "environment_daily",
    "program_enrollment",
}

_FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Merge,
    exp.Grant,
)


class SqlGuardError(ValueError):
    """Raised when a query violates the guard policy."""


def guard_sql(sql: str, *, row_limit: int = 200) -> str:
    """Validate and normalize an LLM-drafted query. Returns safe SQL to execute.

    Raises SqlGuardError with an actionable message (fed back to the agent for
    self-correction).
    """
    try:
        statements = sqlglot.parse(sql, read="bigquery")
    except sqlglot.errors.ParseError as e:
        raise SqlGuardError(f"SQL failed to parse: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SqlGuardError("exactly one SQL statement is allowed")
    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise SqlGuardError("only SELECT queries are allowed")

    forbidden = list(stmt.find_all(*_FORBIDDEN))
    if forbidden:
        raise SqlGuardError(
            f"forbidden operation: {forbidden[0].key.upper()} — queries must be read-only"
        )

    cte_names = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        name = table.name
        if name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            raise SqlGuardError(
                f"table '{name}' is not allowed; use only: {', '.join(sorted(ALLOWED_TABLES))}"
            )

    # Enforce a row cap unless the query already has a stricter one.
    existing = stmt.args.get("limit")
    if existing is None:
        stmt = stmt.limit(row_limit)

    return stmt.sql(dialect="bigquery")

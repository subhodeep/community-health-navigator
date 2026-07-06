"""BigQuery tools for AnalyticsAgent: schema doc + guarded query execution.

Tool errors are returned as {"error": ...} (not raised) so the LLM can
self-correct — the agent instruction allows up to 2 retries.
"""
from __future__ import annotations

import datetime
import decimal
import logging
from typing import Any

from google.adk.tools import ToolContext
from google.cloud import bigquery

from shared.config import load_config
from validators.sql_guard import SqlGuardError, guard_sql

logger = logging.getLogger(__name__)

_client: bigquery.Client | None = None


def _bq() -> bigquery.Client:
    global _client
    if _client is None:
        cfg = load_config()
        _client = bigquery.Client(project=cfg.project_id or None)
    return _client


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


SCHEMA_DOC = """Dataset: community_health (BigQuery Standard SQL; use unqualified table names).

TABLE facilities — registry of care and wellness locations
  facility_id STRING, name STRING, category STRING (clinic|hospital|pharmacy|community_center),
  services ARRAY<STRING> (e.g. 'flu_shot','dental','cardiology','screening','counseling'),
  address STRING, zip STRING, district STRING (D1..D6), lat FLOAT64, lon FLOAT64,
  hours STRING (JSON text), accepts ARRAY<STRING> ('medicaid','uninsured','sliding_scale','private'),
  cost_tier STRING (free|low|standard)
  NOTE: to filter arrays use e.g.  'flu_shot' IN UNNEST(services)  or  'medicaid' IN UNNEST(accepts)

TABLE utilization_daily — daily visit volumes per facility
  date DATE, facility_id STRING, visit_type STRING (er|urgent|primary|wellness),
  visits INT64, avg_wait_minutes FLOAT64

TABLE environment_daily — daily environmental signals per district
  date DATE, district STRING, aqi INT64, pollen_index INT64, heat_index FLOAT64

TABLE program_enrollment — weekly wellness-program enrollment per district
  date DATE, program_id STRING, program_name STRING, district STRING,
  enrollments INT64, capacity INT64

Join key: utilization_daily.facility_id = facilities.facility_id (facilities carries district).
Data covers the last ~12 months.
"""


def get_schema() -> str:
    """Return the BigQuery schema documentation for the community_health dataset.

    Call this before writing any SQL so table and column names are exact.
    """
    return SCHEMA_DOC


def run_bigquery(sql: str, tool_context: ToolContext) -> dict:
    """Execute a read-only BigQuery Standard SQL SELECT against community_health.

    Args:
        sql: A single SELECT statement using only the documented tables.

    Returns:
        {"rows": [...], "row_count": int, "sql": str} on success, or
        {"error": str} describing what to fix — revise the SQL and retry (max 2 retries).
    """
    cfg = load_config()
    try:
        guarded = guard_sql(sql, row_limit=cfg.bigquery.row_limit)
    except SqlGuardError as e:
        return {"error": f"query rejected: {e}"}

    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=cfg.bigquery.max_bytes_billed,
        default_dataset=f"{_bq().project}.{cfg.bigquery.dataset}",
    )
    try:
        job = _bq().query(guarded, job_config=job_config)
        rows = [_jsonable(dict(r)) for r in job.result(timeout=cfg.limits.tool_timeout_s)]
    except Exception as e:  # surface BQ errors to the agent for self-correction
        logger.warning("BigQuery error for sql=%r: %s", guarded, e)
        return {"error": f"BigQuery error: {e}"}

    rows = rows[: cfg.bigquery.row_limit]
    # Stash for render_chart_spec so 200 rows never round-trip through the LLM.
    tool_context.state["last_rows"] = rows
    tool_context.state["last_sql"] = guarded
    return {"rows": rows, "row_count": len(rows), "sql": guarded}

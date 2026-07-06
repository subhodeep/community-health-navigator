"""ForecastAgent tool: parameterized ML.FORECAST — the agent never writes forecast SQL."""
from __future__ import annotations

import logging

from google.adk.tools import ToolContext

from shared.config import load_config
from tools.bigquery import _bq, _jsonable

logger = logging.getLogger(__name__)

SUPPORTED_METRICS = {"visits": "demand_forecast"}


def run_forecast(metric: str, horizon_days: int = 28, tool_context: ToolContext = None) -> dict:
    """Forecast a community health metric per district using the trained model.

    Args:
        metric: metric to forecast. Supported: 'visits' (daily clinic visit demand).
        horizon_days: days ahead to forecast (1–90, default 28).

    Returns:
        {"rows": [{date, district, forecast_visits, lower_bound, upper_bound}],
         "confidence_level": 0.9} or {"error": str}.
    """
    cfg = load_config()
    model = SUPPORTED_METRICS.get(metric)
    if model is None:
        return {
            "error": f"UnsupportedMetric: '{metric}' has no trained model. "
            f"Forecastable metrics: {', '.join(SUPPORTED_METRICS)}"
        }
    horizon = max(1, min(int(horizon_days), 90))
    sql = f"""
        SELECT CAST(forecast_timestamp AS DATE) AS date,
               time_series_id AS district,
               ROUND(forecast_value, 1) AS forecast_visits,
               ROUND(prediction_interval_lower_bound, 1) AS lower_bound,
               ROUND(prediction_interval_upper_bound, 1) AS upper_bound
        FROM ML.FORECAST(MODEL `{cfg.bigquery.dataset}.demand_forecast`,
                         STRUCT({horizon} AS horizon, 0.9 AS confidence_level))
        ORDER BY district, date
    """
    try:
        rows = [_jsonable(dict(r)) for r in _bq().query(sql).result(timeout=cfg.limits.tool_timeout_s)]
    except Exception as e:
        logger.warning("forecast failed: %s", e)
        return {"error": f"forecast unavailable: {e}"}

    tool_context.state["last_rows"] = rows
    tool_context.state["last_sql"] = None  # parameterized, not agent-authored
    return {"rows": rows, "row_count": len(rows), "confidence_level": 0.9}

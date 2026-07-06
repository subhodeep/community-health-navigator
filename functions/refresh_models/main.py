"""Cloud Function (gen2, HTTP): refresh the BigQuery ML demand-forecast model.

Runs CREATE OR REPLACE MODEL ``{dataset}.demand_forecast`` (ARIMA_PLUS over
daily visits per district — architecture.md §5.1) and waits for completion.
Triggered weekly by Cloud Scheduler (§6.6) or manually.

Deployed standalone — does not import shared/.

Env:
- GOOGLE_CLOUD_PROJECT (required in local runs; injected on Cloud Functions).
- BQ_DATASET (optional, default "community_health").
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Tuple

import functions_framework
from google.cloud import bigquery


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": datetime.now(timezone.utc).isoformat(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.getLogger().handlers[:] = [_handler]
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("refresh_models")


def _model_sql(project: str, dataset: str) -> str:
    ds = f"`{project}.{dataset}`" if project else f"`{dataset}`"
    return f"""
CREATE OR REPLACE MODEL {ds}.demand_forecast
OPTIONS(
  model_type='ARIMA_PLUS',
  time_series_timestamp_col='date',
  time_series_data_col='visits',
  time_series_id_col='district'
) AS
SELECT date, district, SUM(visits) AS visits
FROM {ds}.utilization_daily u
JOIN {ds}.facilities f ON u.facility_id = f.facility_id
GROUP BY date, district
"""


@functions_framework.http
def refresh(request) -> Tuple[str, int, dict[str, str]]:
    """HTTP entry point: rebuild demand_forecast, wait, and report status."""
    headers = {"Content-Type": "application/json"}
    dataset = os.environ.get("BQ_DATASET", "community_health")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
    client = bigquery.Client(project=project)

    sql = _model_sql(client.project, dataset)
    logger.info(f"refreshing model {client.project}.{dataset}.demand_forecast")
    try:
        job = client.query(sql)
        job.result()  # CREATE MODEL is long-running; wait for completion
    except Exception as exc:
        logger.exception("model refresh failed")
        body = {
            "model": f"{client.project}.{dataset}.demand_forecast",
            "status": "error",
            "error": str(exc),
        }
        return json.dumps(body), 500, headers

    body = {
        "model": f"{client.project}.{dataset}.demand_forecast",
        "status": "refreshed",
        "job_id": job.job_id,
        "started": job.started.isoformat() if job.started else None,
        "ended": job.ended.isoformat() if job.ended else None,
    }
    logger.info(f"model refresh complete: job {job.job_id}")
    return json.dumps(body), 200, headers

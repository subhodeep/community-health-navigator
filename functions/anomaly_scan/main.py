"""Cloud Function (gen2, HTTP): daily anomaly & threshold scan.

Two checks (architecture.md §5.1, §6.6):
1. ML.DETECT_ANOMALIES over the ARIMA_PLUS demand_forecast model against the
   last 30 days of per-district visits — flags demand anomalies.
2. Latest environment_daily rows where AQI >= 100 — flags air-quality alerts.

Each finding is published to the ALERT_TOPIC Pub/Sub topic as an AlertEvent
JSON payload with the message attribute kind="alert", which routes it to the
Workflow Worker's alert fan-out handler.

Deployed standalone — does not import shared/. The payload shape below must
stay consistent with shared/schemas.py::AlertEvent:
    {signal: "demand_anomaly"|"aqi", district, date, value, detail}

Env:
- GOOGLE_CLOUD_PROJECT (required in local runs; injected on Cloud Functions).
- BQ_DATASET (optional, default "community_health").
- ALERT_TOPIC (optional, default "alert-events").
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Tuple

import functions_framework
from google.cloud import bigquery, pubsub_v1

AQI_ALERT_THRESHOLD = 100
ANOMALY_PROB_THRESHOLD = 0.95
LOOKBACK_DAYS = 30


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
logger = logging.getLogger("anomaly_scan")


def _demand_anomalies(client: bigquery.Client, dataset: str) -> list[dict[str, Any]]:
    """AlertEvent payloads for demand anomalies flagged by ML.DETECT_ANOMALIES."""
    ds = f"`{client.project}.{dataset}`"
    sql = f"""
SELECT *
FROM ML.DETECT_ANOMALIES(
  MODEL {ds}.demand_forecast,
  STRUCT({ANOMALY_PROB_THRESHOLD} AS anomaly_prob_threshold),
  (
    SELECT date, district, SUM(visits) AS visits
    FROM {ds}.utilization_daily u
    JOIN {ds}.facilities f ON u.facility_id = f.facility_id
    WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL {LOOKBACK_DAYS} DAY)
    GROUP BY date, district
  )
)
WHERE is_anomaly
"""
    events: list[dict[str, Any]] = []
    for row in client.query(sql).result():
        prob = float(row["anomaly_probability"] or 0.0)
        events.append(
            {
                "signal": "demand_anomaly",
                "district": str(row["district"]),
                "date": str(row["date"]),
                "value": float(row["visits"] or 0.0),
                "detail": (
                    f"Daily visits deviated from the ARIMA_PLUS forecast "
                    f"(anomaly probability {prob:.3f}, expected range "
                    f"{float(row['lower_bound'] or 0.0):.1f}-"
                    f"{float(row['upper_bound'] or 0.0):.1f})."
                ),
            }
        )
    return events


def _aqi_exceedances(client: bigquery.Client, dataset: str) -> list[dict[str, Any]]:
    """AlertEvent payloads for the latest districts at or above the AQI threshold."""
    ds = f"`{client.project}.{dataset}`"
    sql = f"""
SELECT date, district, aqi
FROM {ds}.environment_daily
WHERE date = (SELECT MAX(date) FROM {ds}.environment_daily)
  AND aqi >= {AQI_ALERT_THRESHOLD}
"""
    events: list[dict[str, Any]] = []
    for row in client.query(sql).result():
        aqi = int(row["aqi"])
        events.append(
            {
                "signal": "aqi",
                "district": str(row["district"]),
                "date": str(row["date"]),
                "value": float(aqi),
                "detail": f"Air quality index reached {aqi} (unhealthy threshold {AQI_ALERT_THRESHOLD}).",
            }
        )
    return events


def _publish_events(
    publisher: pubsub_v1.PublisherClient, topic_path: str, events: list[dict[str, Any]]
) -> int:
    """Publish each AlertEvent with attribute kind="alert"; return count published."""
    futures = [
        publisher.publish(
            topic_path,
            json.dumps(event).encode("utf-8"),
            kind="alert",
        )
        for event in events
    ]
    for future in futures:
        future.result(timeout=30)  # raises on publish failure
    return len(futures)


@functions_framework.http
def scan(request) -> Tuple[str, int, dict[str, str]]:
    """HTTP entry point: run both checks, publish findings, return counts."""
    headers = {"Content-Type": "application/json"}
    dataset = os.environ.get("BQ_DATASET", "community_health")
    topic_id = os.environ.get("ALERT_TOPIC", "alert-events")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or None

    try:
        bq = bigquery.Client(project=project)
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(bq.project, topic_id)

        demand_events = _demand_anomalies(bq, dataset)
        aqi_events = _aqi_exceedances(bq, dataset)
        published = _publish_events(publisher, topic_path, demand_events + aqi_events)
    except Exception as exc:
        logger.exception("anomaly scan failed")
        return json.dumps({"status": "error", "error": str(exc)}), 500, headers

    body = {
        "status": "ok",
        "topic": topic_path,
        "demand_anomalies": len(demand_events),
        "aqi_exceedances": len(aqi_events),
        "published": published,
    }
    logger.info(
        f"anomaly scan complete: {len(demand_events)} demand, "
        f"{len(aqi_events)} aqi, {published} published"
    )
    return json.dumps(body), 200, headers

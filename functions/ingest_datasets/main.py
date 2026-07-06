"""Cloud Function (gen2, HTTP): load JSONL seed files from GCS into BigQuery.

Loads gs://{DATA_BUCKET}/seed/{table}.jsonl into the ``community_health``
dataset for each known table, with WRITE_TRUNCATE + schema autodetect.
Triggered nightly by Cloud Scheduler (architecture.md §6.6) or manually.

Deployed standalone — does not import shared/. Table names mirror the DDL in
architecture.md §5.1.

Env:
- DATA_BUCKET (required): bucket holding seed/{table}.jsonl files.
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
from google.api_core import exceptions as gapi_exceptions
from google.cloud import bigquery

TABLES: tuple[str, ...] = (
    "facilities",
    "utilization_daily",
    "environment_daily",
    "program_enrollment",
)


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
logger = logging.getLogger("ingest_datasets")


def _load_table(
    client: bigquery.Client, bucket: str, dataset: str, table: str
) -> dict[str, Any]:
    """Run one GCS→BigQuery load job; return a per-table result dict."""
    uri = f"gs://{bucket}/seed/{table}.jsonl"
    table_ref = f"{client.project}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )
    load_job = client.load_table_from_uri(uri, table_ref, job_config=job_config)
    load_job.result()  # wait; raises on failure
    row_count = client.get_table(table_ref).num_rows
    logger.info(f"loaded {row_count} rows from {uri} into {table_ref}")
    return {"status": "loaded", "source": uri, "rows": int(row_count)}


@functions_framework.http
def ingest(request) -> Tuple[str, int, dict[str, str]]:
    """HTTP entry point: load every seed table; return per-table row counts."""
    headers = {"Content-Type": "application/json"}

    bucket = os.environ.get("DATA_BUCKET", "")
    if not bucket:
        logger.error("DATA_BUCKET env var is not set")
        return json.dumps({"error": "DATA_BUCKET env var is required"}), 500, headers

    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
    dataset = os.environ.get("BQ_DATASET", "community_health")
    client = bigquery.Client(project=project)

    results: dict[str, Any] = {}
    failed = False
    for table in TABLES:
        try:
            results[table] = _load_table(client, bucket, dataset, table)
        except gapi_exceptions.NotFound as exc:
            # Missing seed file or dataset: report per-table, keep loading the rest.
            failed = True
            logger.warning(f"load skipped for {table}: {exc}")
            results[table] = {"status": "not_found", "error": str(exc)}
        except Exception as exc:
            failed = True
            logger.exception(f"load failed for {table}")
            results[table] = {"status": "error", "error": str(exc)}

    body = {"dataset": dataset, "bucket": bucket, "tables": results}
    return json.dumps(body), (500 if failed else 200), headers

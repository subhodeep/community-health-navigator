"""Cloud Function (gen2): re-import the docs corpus into Vertex AI Search.

Two entry points in one deployable source dir:
- ``reindex`` (CloudEvent, GCS object-finalize): fires when a document lands
  under the ``docs/`` prefix of the knowledge bucket; kicks off an INCREMENTAL
  import of ``gs://{bucket}/docs/*`` into the datastore (architecture.md §5.2).
- ``reindex_http`` (HTTP): manual trigger for the same import; bucket comes
  from the ``bucket`` query param / JSON field or the DATA_BUCKET env var.

Deployed standalone — does not import shared/.

Env:
- GOOGLE_CLOUD_PROJECT (required in local runs; injected on Cloud Functions).
- DATASTORE_ID (optional, default "health-knowledge").
- DATA_BUCKET (optional; fallback bucket for reindex_http).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Tuple

import functions_framework
from google.cloud import discoveryengine_v1 as discoveryengine

DOCS_PREFIX = "docs/"


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
logger = logging.getLogger("reindex_docs")


def _datastore_parent() -> str:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var is required")
    datastore_id = os.environ.get("DATASTORE_ID", "health-knowledge")
    return (
        f"projects/{project}/locations/global/collections/default_collection"
        f"/dataStores/{datastore_id}/branches/default_branch"
    )


def _start_import(bucket: str) -> str:
    """Start an INCREMENTAL import of gs://{bucket}/docs/*; return the LRO name."""
    client = discoveryengine.DocumentServiceClient()
    import_request = discoveryengine.ImportDocumentsRequest(
        parent=_datastore_parent(),
        gcs_source=discoveryengine.GcsSource(
            input_uris=[f"gs://{bucket}/{DOCS_PREFIX}*"],
            data_schema="content",
        ),
        reconciliation_mode=(
            discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL
        ),
    )
    # Imports run for minutes; return the operation name rather than blocking
    # the function on completion. Progress is visible in the console / via LRO.
    operation = client.import_documents(request=import_request)
    return operation.operation.name


@functions_framework.cloud_event
def reindex(cloud_event) -> None:
    """GCS object-finalize trigger: reindex when a doc lands under docs/."""
    data = cloud_event.data or {}
    bucket = data.get("bucket", "")
    name = data.get("name", "")

    if not bucket or not name.startswith(DOCS_PREFIX):
        logger.info(f"ignoring finalize event outside {DOCS_PREFIX}: gs://{bucket}/{name}")
        return

    operation_name = _start_import(bucket)
    logger.info(
        f"import started for gs://{bucket}/{DOCS_PREFIX}* "
        f"(trigger: {name}, operation: {operation_name})"
    )


@functions_framework.http
def reindex_http(request) -> Tuple[str, int, dict[str, str]]:
    """Manual HTTP trigger for the same import."""
    headers = {"Content-Type": "application/json"}

    body = request.get_json(silent=True) or {}
    bucket = (
        request.args.get("bucket")
        or body.get("bucket")
        or os.environ.get("DATA_BUCKET", "")
    )
    if not bucket:
        return (
            json.dumps({"error": "provide ?bucket= or set DATA_BUCKET env var"}),
            400,
            headers,
        )

    try:
        operation_name = _start_import(bucket)
    except Exception as exc:
        logger.exception("manual reindex failed")
        return json.dumps({"status": "error", "error": str(exc)}), 500, headers

    logger.info(f"manual import started for gs://{bucket}/{DOCS_PREFIX}*")
    return (
        json.dumps(
            {
                "status": "import_started",
                "source": f"gs://{bucket}/{DOCS_PREFIX}*",
                "operation": operation_name,
            }
        ),
        200,
        headers,
    )

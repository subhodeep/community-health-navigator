"""Workflow Worker — Pub/Sub push consumer (Cloud Run).

Receives Pub/Sub push envelopes on POST /push, decodes the payload, and routes
by the message attribute ``kind``:

- ``kind == "intent"`` (default): an action intent published by the agent's
  ActionAgent (referral or alert_subscription). Re-validated against
  ``shared.schemas`` and executed by the matching handler.
- ``kind == "alert"``: an ``AlertEvent`` published by the anomaly_scan Cloud
  Function; fanned out to matching Firestore subscriptions.

Response semantics (architecture.md §11):
- 204 — success; Pub/Sub acks the message.
- 204 + warning + audit record — permanently-invalid ("poison") payloads.
  These must NOT be retried forever, so we ack after logging and auditing.
- 500 — transient failure (Firestore/network); Pub/Sub redelivers, and the
  handlers are idempotent on ``intent_id`` so redelivery is safe.
"""
from __future__ import annotations

import base64
import binascii
import functools
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from google.api_core import exceptions as gapi_exceptions
from google.cloud import firestore
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from shared.schemas import AlertEvent, AlertSubscriptionIntent, ReferralIntent, parse_intent

from handlers import alerts as alerts_handler
from handlers import referral as referral_handler
from handlers import subscription as subscription_handler

# ---------------------------------------------------------------------------
# Structured (JSON) logging
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """Render every log record as a single JSON line (Cloud Logging friendly)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": datetime.now(timezone.utc).isoformat(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "json_fields", None)
        if isinstance(extra, dict):
            entry.update(extra)
        return json.dumps(entry, default=str)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


_configure_logging()
logger = logging.getLogger("worker")

app = FastAPI(title="community-health-navigator-worker")


# ---------------------------------------------------------------------------
# Firestore client (lazy singleton)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_db() -> firestore.Client:
    return firestore.Client()


class PoisonMessage(Exception):
    """Payload is permanently invalid — ack (204) after logging + auditing."""


# ---------------------------------------------------------------------------
# Envelope decoding & dispatch
# ---------------------------------------------------------------------------


def _decode_envelope(envelope: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """Return (payload, kind, message_id) from a Pub/Sub push envelope."""
    message = envelope.get("message")
    if not isinstance(message, dict):
        raise PoisonMessage("envelope has no 'message' object")
    message_id = str(message.get("messageId", ""))
    attributes = message.get("attributes") or {}
    kind = attributes.get("kind", "intent")
    try:
        raw = base64.b64decode(message.get("data", ""), validate=True)
        payload = json.loads(raw)
    except (binascii.Error, ValueError) as exc:
        raise PoisonMessage(f"message data is not base64-encoded JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PoisonMessage(f"payload is not a JSON object: {type(payload).__name__}")
    return payload, kind, message_id


def _dispatch(payload: dict[str, Any], kind: str) -> str:
    """Route the decoded payload to its handler. Returns a summary string."""
    db = get_db()
    if kind == "alert":
        try:
            event = AlertEvent.model_validate(payload)
        except ValidationError as exc:
            raise PoisonMessage(f"invalid AlertEvent payload: {exc}") from exc
        notified = alerts_handler.handle(db, event)
        return f"alert {event.signal}/{event.district}: {notified} notification(s)"

    if kind == "intent":
        try:
            intent = parse_intent(payload)
        except (ValidationError, ValueError) as exc:
            raise PoisonMessage(f"invalid intent payload: {exc}") from exc
        if isinstance(intent, ReferralIntent):
            referral_handler.handle(db, intent)
        elif isinstance(intent, AlertSubscriptionIntent):
            subscription_handler.handle(db, intent)
        else:  # parse_intent guarantees the above, but keep the seam explicit
            raise PoisonMessage(f"no handler for intent type {intent.type!r}")
        return f"intent {intent.type}/{intent.intent_id} executed"

    raise PoisonMessage(f"unknown message kind: {kind!r}")


def _audit_poison(message_id: str, kind: str, error: str) -> None:
    """Best-effort audit record for an acked poison message."""
    try:
        get_db().collection("audit").document().set(
            {
                "actor": "worker",
                "action": "poison_message_acked",
                "params": {"message_id": message_id, "kind": kind, "error": error},
                "intent_id": None,
                "status": "rejected",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception:  # audit is best-effort; never turn a poison ack into a retry loop
        logger.exception("failed to write poison-message audit record")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/push")
async def push(request: Request) -> Response:
    kind = "unknown"
    message_id = ""
    try:
        try:
            envelope = await request.json()
        except json.JSONDecodeError as exc:
            raise PoisonMessage(f"request body is not valid JSON: {exc}") from exc
        if not isinstance(envelope, dict):
            raise PoisonMessage("request body is not a JSON object")

        payload, kind, message_id = _decode_envelope(envelope)
        summary = await run_in_threadpool(_dispatch, payload, kind)
        logger.info(
            "message processed",
            extra={"json_fields": {"message_id": message_id, "kind": kind, "summary": summary}},
        )
        return Response(status_code=204)

    except PoisonMessage as exc:
        logger.warning(
            "poison message acked without processing",
            extra={"json_fields": {"message_id": message_id, "kind": kind, "error": str(exc)}},
        )
        await run_in_threadpool(_audit_poison, message_id, kind, str(exc))
        return Response(status_code=204)

    except (gapi_exceptions.GoogleAPICallError, gapi_exceptions.RetryError) as exc:
        logger.error(
            "transient backend error — NACKing for redelivery",
            exc_info=True,
            extra={"json_fields": {"message_id": message_id, "kind": kind, "error": str(exc)}},
        )
        return JSONResponse(status_code=500, content={"error": "transient backend error"})

    except Exception as exc:
        # Unknown failure: treat as transient so Pub/Sub retries; the DLQ
        # (5 attempts, architecture.md §11) bounds pathological cases.
        logger.error(
            "unexpected error — NACKing for redelivery",
            exc_info=True,
            extra={"json_fields": {"message_id": message_id, "kind": kind, "error": str(exc)}},
        )
        return JSONResponse(status_code=500, content={"error": "internal error"})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

"""Execute an AlertSubscriptionIntent: write the subscription doc, notify, audit.

Idempotent on ``intent_id`` — see handlers/referral.py for the rationale.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import firestore

from shared.schemas import AlertSubscriptionIntent

import notifier

logger = logging.getLogger("worker.handlers.subscription")


def handle(db: firestore.Client, intent: AlertSubscriptionIntent) -> None:
    """Write ``subscriptions/{intent_id}``, send confirmation, write audit record."""
    audit_ref = db.collection("audit").document(intent.intent_id)
    snapshot = audit_ref.get()
    if snapshot.exists and snapshot.get("status") == "executed":
        logger.info(
            "subscription intent already executed — skipping",
            extra={"json_fields": {"intent_id": intent.intent_id}},
        )
        return

    now = datetime.now(timezone.utc).isoformat()

    db.collection("subscriptions").document(intent.intent_id).set(
        {
            "user_id": intent.user_id,
            "signal": intent.signal,
            "threshold": intent.threshold,
            "channel": intent.channel,
            "active": True,
            "ts": now,
        }
    )

    notifier.send(
        user_id=intent.user_id,
        subject="Alert subscription confirmed",
        body=(
            f"You're subscribed: we'll email you whenever the {intent.signal} "
            f"signal reaches {intent.threshold} in your district."
        ),
    )

    audit_ref.set(
        {
            "actor": "worker",
            "action": "subscription_executed",
            "intent_id": intent.intent_id,
            "ts": now,
            "status": "executed",
        }
    )
    logger.info(
        "subscription executed",
        extra={
            "json_fields": {
                "intent_id": intent.intent_id,
                "user_id": intent.user_id,
                "signal": intent.signal,
                "threshold": intent.threshold,
            }
        },
    )

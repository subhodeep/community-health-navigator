"""Fan an AlertEvent out to matching alert subscriptions.

For each active subscription on the event's signal whose threshold is at or
below the event value, send a notification and write an audit record.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from shared.schemas import AlertEvent

import notifier

logger = logging.getLogger("worker.handlers.alerts")


def handle(db: firestore.Client, event: AlertEvent) -> int:
    """Notify every matching subscriber. Returns the number of notifications sent."""
    query = (
        db.collection("subscriptions")
        .where(filter=FieldFilter("active", "==", True))
        .where(filter=FieldFilter("signal", "==", event.signal))
    )

    notified = 0
    for doc in query.stream():
        sub = doc.to_dict() or {}
        threshold = float(sub.get("threshold", 0.0))
        user_id = str(sub.get("user_id", ""))
        if not user_id or threshold > event.value:
            continue

        notifier.send(
            user_id=user_id,
            subject=f"{event.signal} alert for {event.district}",
            body=(
                f"{event.signal} alert for {event.district}: value {event.value} "
                f"exceeded your threshold {threshold}."
                + (f" {event.detail}" if event.detail else "")
            ),
        )

        db.collection("audit").document().set(
            {
                "actor": "worker",
                "action": "alert_notified",
                "params": {
                    "subscription_id": doc.id,
                    "user_id": user_id,
                    "signal": event.signal,
                    "district": event.district,
                    "date": event.date,
                    "value": event.value,
                    "threshold": threshold,
                },
                "intent_id": None,
                "status": "executed",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        notified += 1

    logger.info(
        "alert fan-out complete",
        extra={
            "json_fields": {
                "signal": event.signal,
                "district": event.district,
                "value": event.value,
                "notified": notified,
            }
        },
    )
    return notified

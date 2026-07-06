"""Execute a ReferralIntent: write the referral doc, notify, audit.

Idempotent on ``intent_id`` (architecture.md §11): Pub/Sub is at-least-once,
so a redelivered intent whose audit record already shows ``executed`` is
skipped without side-effects.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import firestore

from shared.schemas import ReferralIntent

import notifier

logger = logging.getLogger("worker.handlers.referral")


def handle(db: firestore.Client, intent: ReferralIntent) -> None:
    """Write ``referrals/{intent_id}``, send confirmation, write audit record."""
    audit_ref = db.collection("audit").document(intent.intent_id)
    snapshot = audit_ref.get()
    if snapshot.exists and snapshot.get("status") == "executed":
        logger.info(
            "referral intent already executed — skipping",
            extra={"json_fields": {"intent_id": intent.intent_id}},
        )
        return

    now = datetime.now(timezone.utc).isoformat()

    db.collection("referrals").document(intent.intent_id).set(
        {
            "user_id": intent.user_id,
            "specialty": intent.specialty,
            "facility_id": intent.facility_id,
            "status": "received",
            "notes": intent.notes,
            "ts": now,
        }
    )

    facility = f" at facility {intent.facility_id}" if intent.facility_id else ""
    notifier.send(
        user_id=intent.user_id,
        subject="Referral request received",
        body=(
            f"Your referral request for {intent.specialty}{facility} has been "
            "received. You'll be notified when a provider match is confirmed."
        ),
    )

    audit_ref.set(
        {
            "actor": "worker",
            "action": "referral_executed",
            "intent_id": intent.intent_id,
            "ts": now,
            "status": "executed",
        }
    )
    logger.info(
        "referral executed",
        extra={
            "json_fields": {
                "intent_id": intent.intent_id,
                "user_id": intent.user_id,
                "specialty": intent.specialty,
                "facility_id": intent.facility_id,
            }
        },
    )

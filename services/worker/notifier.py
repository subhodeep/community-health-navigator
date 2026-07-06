"""Notification stub for the MVP (architecture.md §6.4).

Emits a structured JSON log line per notification instead of sending real
email. In production this module would hand off to a transactional email
provider (SendGrid / Amazon SES) — ideally via Cloud Tasks so sends get their
own retry budget independent of Pub/Sub message processing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("worker.notifier")


def send(user_id: str, subject: str, body: str) -> None:
    """"Send" an email notification by logging it as a structured JSON line."""
    logger.info(
        json.dumps(
            {
                "notification": {
                    "channel": "email",
                    "user_id": user_id,
                    "subject": subject,
                    "body": body,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            }
        )
    )

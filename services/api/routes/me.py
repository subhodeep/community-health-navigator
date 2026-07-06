"""GET /api/v1/me/items — the caller's referrals and alert subscriptions."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth import User, get_user
from deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

_LIMIT = 20


def _serialize(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"id": doc_id}
    for key, value in data.items():
        out[key] = value.isoformat() if isinstance(value, datetime) else value
    return out


async def _user_items(collection: str, user_id: str) -> list[dict[str, Any]]:
    query = (
        get_db()
        .collection(collection)
        .where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("ts", direction=firestore.Query.DESCENDING)
        .limit(_LIMIT)
    )
    return [_serialize(doc.id, doc.to_dict() or {}) async for doc in query.stream()]


@router.get("/me/items")
async def my_items(user: User = Depends(get_user)) -> dict[str, list[dict[str, Any]]]:
    """Return the caller's 20 most recent referrals and subscriptions."""
    return {
        "referrals": await _user_items("referrals", user.user_id),
        "subscriptions": await _user_items("subscriptions", user.user_id),
    }

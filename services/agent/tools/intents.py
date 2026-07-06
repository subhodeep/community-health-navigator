"""ActionAgent tools: two-phase (stage -> user confirms -> publish) workflow intents.

Publishing only emits a typed Pub/Sub message + audit record; the Workflow
Worker performs all side-effects (Firestore writes, notifications).
"""
from __future__ import annotations

import datetime
import json
import logging
import uuid

from google.adk.tools import ToolContext
from google.cloud import firestore, pubsub_v1

from shared.config import load_config
from shared.schemas import parse_intent

logger = logging.getLogger(__name__)

_publisher: pubsub_v1.PublisherClient | None = None
_db: firestore.Client | None = None


def _pub() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _fs() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=load_config().project_id or None)
    return _db


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def stage_action(action_type: str, params_json: str, tool_context: ToolContext) -> dict:
    """Stage an action for the user to confirm. NEVER publishes anything itself.

    Args:
        action_type: 'referral' (params: specialty, facility_id, notes) or
            'alert_subscription' (params: signal 'aqi'|'demand_anomaly',
            threshold number, channel 'email').
        params_json: JSON object string with the params for the action type.

    Returns:
        {"staged": True, "confirm_token": str, "params": dict} — now ask the
        user to confirm in plain language, or {"error": str}.
    """
    if action_type not in ("referral", "alert_subscription"):
        return {"error": "action_type must be 'referral' or 'alert_subscription'"}
    try:
        params = json.loads(params_json)
        assert isinstance(params, dict)
    except (json.JSONDecodeError, AssertionError):
        return {"error": "params_json must be a JSON object string"}

    pending = {
        "intent": action_type,
        "params": params,
        "confirm_token": uuid.uuid4().hex[:12],
    }
    tool_context.state["pending_action"] = pending
    return {"staged": True, **pending}


def confirm_pending_action(tool_context: ToolContext) -> dict:
    """Publish the staged action AFTER the user has explicitly said yes.

    Returns:
        {"published": True, "intent_id": str} or {"error": str}.
    """
    pending = tool_context.state.get("pending_action")
    if not pending:
        return {"error": "no pending action — stage one first"}

    cfg = load_config()
    user_id = tool_context.state.get("user_id", "unknown")
    intent_id = f"int_{uuid.uuid4().hex[:16]}"
    payload = {
        **pending["params"],
        "type": pending["intent"],
        "intent_id": intent_id,
        "user_id": user_id,
        "issued_at": _now(),
    }
    try:
        intent = parse_intent(payload)  # schema-validate before anything leaves the agent
    except Exception as e:
        return {"error": f"invalid action parameters: {e}"}

    topic = _pub().topic_path(cfg.project_id, cfg.topics.action_intents)
    try:
        _pub().publish(topic, intent.model_dump_json().encode("utf-8"), kind="intent").result(
            timeout=cfg.limits.tool_timeout_s
        )
        _fs().collection("audit").document(intent_id).set(
            {
                "actor": user_id,
                "action": f"intent_published:{intent.type}",
                "params": pending["params"],
                "intent_id": intent_id,
                "status": "published",
                "ts": _now(),
            }
        )
    except Exception as e:
        logger.exception("intent publish failed")
        return {"error": f"could not submit the request: {e}"}

    tool_context.state["pending_action"] = None
    return {"published": True, "intent_id": intent_id, "type": intent.type}


def cancel_pending_action(tool_context: ToolContext) -> dict:
    """Discard the staged action when the user declines or changes their mind."""
    tool_context.state["pending_action"] = None
    return {"cancelled": True}


def list_my_items(tool_context: ToolContext) -> dict:
    """List the current user's referral requests and alert subscriptions.

    Returns:
        {"referrals": [...], "subscriptions": [...]} (most recent first, max 10 each).
    """
    user_id = tool_context.state.get("user_id", "unknown")
    out: dict = {"referrals": [], "subscriptions": []}
    try:
        for coll in ("referrals", "subscriptions"):
            docs = (
                _fs()
                .collection(coll)
                .where("user_id", "==", user_id)
                .limit(10)
                .stream()
            )
            out[coll] = [{**d.to_dict(), "id": d.id} for d in docs]
    except Exception as e:
        logger.warning("list_my_items failed: %s", e)
        return {"error": f"could not load items: {e}"}
    return out

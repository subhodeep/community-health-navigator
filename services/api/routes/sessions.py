"""Session endpoints: create a session (via the agent service) and read history."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import User, get_user
from deps import agent_url, get_db
from shared.schemas import CreateSessionRequest, CreateSessionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateSessionBody(BaseModel):
    persona: Optional[Literal["citizen", "analyst"]] = None


def _serialize(value: Any) -> Any:
    """Recursively convert Firestore values (datetimes) to JSON-safe types."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


@router.post("/sessions")
async def create_session(
    body: CreateSessionBody, user: User = Depends(get_user)
) -> dict[str, str]:
    """Create a new conversation session via the agent service."""
    persona = body.persona or user.persona
    payload = CreateSessionRequest(user_id=user.user_id, persona=persona)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{agent_url()}/sessions", json=payload.model_dump()
            )
            resp.raise_for_status()
    except httpx.HTTPError:
        logger.error("agent session creation failed", exc_info=True)
        raise HTTPException(status_code=502, detail="assistant unavailable")
    session_id = CreateSessionResponse.model_validate(resp.json()).session_id
    # Defensive ownership merge — the agent service owns the canonical doc.
    await get_db().collection("sessions").document(session_id).set(
        {"user_id": user.user_id, "persona": persona}, merge=True
    )
    return {"session_id": session_id}


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str, user: User = Depends(get_user)
) -> list[dict[str, Any]]:
    """Return the session's messages ordered by ts; caller must own the session."""
    db = get_db()
    session_ref = db.collection("sessions").document(session_id)
    snapshot = await session_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="session not found")
    if (snapshot.to_dict() or {}).get("user_id") != user.user_id:
        raise HTTPException(status_code=403, detail="not your session")

    messages: list[dict[str, Any]] = []
    async for doc in session_ref.collection("messages").order_by("ts").stream():
        messages.append(_serialize(doc.to_dict() or {}))
    return messages

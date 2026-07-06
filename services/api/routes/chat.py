"""POST /api/v1/chat — SSE stream-proxy of the agent service's /run endpoint.

Auto-creates a session when none is supplied, persists both sides of the turn
to Firestore, and forwards the agent's SSE stream verbatim while parsing it
on the side (see sse.StreamAccumulator).
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import firestore
from pydantic import BaseModel

from auth import User, get_user
from deps import agent_url, get_db
from sse import StreamAccumulator, format_sse
from shared.schemas import CreateSessionRequest, CreateSessionResponse, RunRequest

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    image_uri: Optional[str] = None
    persona: Optional[Literal["citizen", "analyst"]] = None


async def _create_session(user_id: str, persona: str) -> str:
    """Create a session via the agent service and defensively merge-write ownership."""
    payload = CreateSessionRequest(user_id=user_id, persona=persona)
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
    await get_db().collection("sessions").document(session_id).set(
        {"user_id": user_id, "persona": persona}, merge=True
    )
    return session_id


async def _persist_user_message(session_id: str, body: ChatRequest) -> None:
    await get_db().collection("sessions").document(session_id).collection(
        "messages"
    ).add(
        {
            "role": "user",
            "content": body.message,
            "image_uri": body.image_uri,
            "ts": firestore.SERVER_TIMESTAMP,
        }
    )


async def _persist_assistant_message(session_id: str, acc: StreamAccumulator) -> None:
    if not acc.has_content:
        return
    doc = {
        "role": "assistant",
        "content": acc.content,
        "citations": acc.citations,
        "chart_spec": acc.chart_spec,
        "ts": firestore.SERVER_TIMESTAMP,
    }
    if not acc.done_seen:
        doc["interrupted"] = True
    try:
        await get_db().collection("sessions").document(session_id).collection(
            "messages"
        ).add(doc)
    except Exception:  # persistence must never break/interleave the stream teardown
        logger.error("failed to persist assistant message", exc_info=True)


@router.post("/chat")
async def chat(body: ChatRequest, user: User = Depends(get_user)) -> StreamingResponse:
    """Run one conversational turn, streaming public SSE events to the client."""
    persona = body.persona or user.persona
    session_created = body.session_id is None
    session_id = body.session_id or await _create_session(user.user_id, persona)

    await _persist_user_message(session_id, body)

    run_request = RunRequest(
        session_id=session_id,
        user_id=user.user_id,
        persona=persona,
        message=body.message,
        image_uri=body.image_uri,
    )

    async def event_stream() -> AsyncIterator[str]:
        if session_created:
            yield format_sse("session", {"session_id": session_id})
        acc = StreamAccumulator()
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", f"{agent_url()}/run", json=run_request.model_dump()
                ) as resp:
                    if resp.status_code != 200:
                        logger.error("agent /run returned %s", resp.status_code)
                        yield format_sse(
                            "error",
                            {"message": "assistant unavailable", "code": "upstream"},
                        )
                        yield format_sse("done", {"latency_ms": 0, "agents_used": []})
                        return
                    async for line in resp.aiter_lines():
                        acc.feed(line)
                        yield f"{line}\n"
        except httpx.HTTPError:
            logger.error("agent /run stream failed", exc_info=True)
            yield format_sse(
                "error", {"message": "assistant unavailable", "code": "upstream"}
            )
            yield format_sse("done", {"latency_ms": 0, "agents_used": []})
        finally:
            await _persist_assistant_message(session_id, acc)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

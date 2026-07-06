"""Agent Service — hosts the ADK runner behind an internal HTTP contract.

POST /sessions  create an ADK session (called by the API service)
POST /run       execute one turn, streaming SSE events (token/citations/
                chart_spec/action_request/error/done) per shared.schemas
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.genai import types

from agents.navigator import build_navigator
from sessions.firestore_session_service import FirestoreSessionService
from shared.schemas import CreateSessionRequest, CreateSessionResponse, RunRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_NAME = "community-health-navigator"
_TRANSIENT_KEYS = ["citations", "chart_spec", "last_rows", "last_sql"]

app = FastAPI(title="CHN Agent Service")
_runner: Runner | None = None


def get_runner() -> Runner:
    global _runner
    if _runner is None:
        _runner = Runner(
            agent=build_navigator(),
            app_name=APP_NAME,
            session_service=FirestoreSessionService(),
        )
    return _runner


def _sse(event: str, data: Any) -> str:
    return f"data: {json.dumps({'event': event, 'data': data}, default=str)}\n\n"


def _guess_mime(uri: str) -> str:
    return "image/png" if uri.lower().endswith(".png") else "image/jpeg"


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/sessions")
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    session = await get_runner().session_service.create_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        state={"user_id": req.user_id, "persona": req.persona},
    )
    return CreateSessionResponse(session_id=session.id)


@app.post("/run")
async def run(req: RunRequest) -> StreamingResponse:
    return StreamingResponse(_run_stream(req), media_type="text/event-stream")


async def _run_stream(req: RunRequest) -> AsyncIterator[str]:
    start = time.monotonic()
    runner = get_runner()
    agents_used: list[str] = []

    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=req.user_id, session_id=req.session_id
    )
    if session is None:
        await runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=req.session_id,
            state={"user_id": req.user_id, "persona": req.persona},
        )

    parts = [types.Part(text=req.message)]
    if req.image_uri:
        parts.append(types.Part.from_uri(file_uri=req.image_uri, mime_type=_guess_mime(req.image_uri)))
    content = types.Content(role="user", parts=parts)

    emitted_final = False
    try:
        async for event in runner.run_async(
            user_id=req.user_id, session_id=req.session_id, new_message=content
        ):
            author = getattr(event, "author", None)
            if author and author != "user" and author not in agents_used:
                agents_used.append(author)
            if not (event.content and event.content.parts):
                continue
            text = "".join(p.text or "" for p in event.content.parts if getattr(p, "text", None))
            if not text:
                continue
            if getattr(event, "partial", False):
                yield _sse("token", {"text": text})
                emitted_final = True  # streamed incrementally; final event repeats the text
            elif event.is_final_response() and not emitted_final:
                yield _sse("token", {"text": text})
    except Exception:
        logger.exception("agent run failed (session=%s)", req.session_id)
        yield _sse(
            "error",
            {"message": "The assistant hit an internal error — please try again.", "code": "agent"},
        )

    # Structured extras written by tools into session state during the turn.
    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=req.user_id, session_id=req.session_id
    )
    if session:
        state = session.state or {}
        if state.get("citations"):
            yield _sse("citations", state["citations"])
        if state.get("chart_spec"):
            yield _sse("chart_spec", state["chart_spec"])
        if state.get("pending_action"):
            pa = state["pending_action"]
            yield _sse(
                "action_request",
                {"intent": pa["intent"], "params": pa["params"], "confirm_token": pa["confirm_token"]},
            )
        # Clear per-turn keys so the next turn doesn't re-emit stale artifacts.
        svc = runner.session_service
        if isinstance(svc, FirestoreSessionService):
            await svc.clear_state_keys(req.session_id, _TRANSIENT_KEYS)

    yield _sse(
        "done",
        {"latency_ms": int((time.monotonic() - start) * 1000), "agents_used": agents_used},
    )

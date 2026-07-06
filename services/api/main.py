"""Community Health Navigator — public API service (FastAPI, Cloud Run).

Owns HTTP/auth/session concerns and bridges clients to the internal agent
service over SSE. See architecture.md §3, §7.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from deps import agent_url, get_db
from routes import chat, me, sessions, uploads

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Community Health Navigator API", version="0.1.0")

# Hackathon posture: allow all origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(uploads.router, prefix="/api/v1", tags=["uploads"])
app.include_router(me.router, prefix="/api/v1", tags=["me"])


async def _firestore_healthy() -> bool:
    try:
        await get_db().collection("sessions").limit(1).get()
        return True
    except Exception:
        logger.warning("healthz: firestore check failed", exc_info=True)
        return False


async def _agent_healthy() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{agent_url()}/healthz")
        return resp.status_code == 200
    except Exception:
        logger.warning("healthz: agent check failed", exc_info=True)
        return False


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness + dependency report; dependency failures are reported, not raised."""
    return {
        "status": "ok",
        "deps": {
            "firestore": await _firestore_healthy(),
            "agent": await _agent_healthy(),
        },
    }

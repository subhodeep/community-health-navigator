"""Authentication dependency: Firebase ID-token verification or demo headers.

AUTH_MODE=firebase (default): verify the Bearer ID token with firebase_admin;
persona comes from the custom claim "persona" (default "citizen").
AUTH_MODE=demo: identity from X-Demo-User / X-Persona headers (no verification).
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_PERSONAS = ("citizen", "analyst")


class User(BaseModel):
    user_id: str
    persona: Literal["citizen", "analyst"] = "citizen"


def _coerce_persona(value: object) -> str:
    return value if value in _PERSONAS else "citizen"


def _verify_firebase_token(token: str) -> User:
    """Verify a Firebase ID token; raises on any verification failure."""
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if not firebase_admin._apps:  # lazy init with default credentials
        firebase_admin.initialize_app()
    decoded = fb_auth.verify_id_token(token)
    return User(
        user_id=decoded["uid"],
        persona=_coerce_persona(decoded.get("persona")),
    )


def get_user(request: Request) -> User:
    """FastAPI dependency resolving the calling user per AUTH_MODE."""
    mode = os.environ.get("AUTH_MODE", "firebase").lower()

    if mode == "demo":
        return User(
            user_id=request.headers.get("X-Demo-User", "demo-user"),
            persona=_coerce_persona(request.headers.get("X-Persona", "citizen")),
        )

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return _verify_firebase_token(header[len("Bearer ") :].strip())
    except HTTPException:
        raise
    except Exception:
        logger.warning("firebase token verification failed", exc_info=True)
        raise HTTPException(status_code=401, detail="invalid token")

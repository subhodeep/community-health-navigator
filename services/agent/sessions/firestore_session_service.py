"""Firestore-backed ADK SessionService.

Layout (matches architecture.md §5.3):
  sessions/{session_id}                 -> {app_name, user_id, state, created_at, updated_at}
  sessions/{session_id}/adk_events/{id} -> {ts, event: <Event JSON>}

Cloud Run instances are ephemeral, so sessions must live outside the process.
"""
from __future__ import annotations

import datetime
import logging
import time
import uuid
from typing import Any, Optional

from google.adk.events import Event
from google.adk.sessions import BaseSessionService, Session
from google.adk.sessions.base_session_service import GetSessionConfig, ListSessionsResponse
from google.cloud import firestore

from shared.config import load_config

logger = logging.getLogger(__name__)

_MAX_EVENTS = 50  # context window for a rehydrated session


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class FirestoreSessionService(BaseSessionService):
    def __init__(self, project: str | None = None) -> None:
        self._db = firestore.AsyncClient(project=project or load_config().project_id or None)

    def _doc(self, session_id: str):
        return self._db.collection("sessions").document(session_id)

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        session_id = session_id or uuid.uuid4().hex
        state = dict(state or {})
        state.setdefault("user_id", user_id)
        await self._doc(session_id).set(
            {
                "app_name": app_name,
                "user_id": user_id,
                "state": state,
                "created_at": _now(),
                "updated_at": _now(),
            },
            merge=True,
        )
        return Session(
            id=session_id, app_name=app_name, user_id=user_id, state=state, events=[],
            last_update_time=time.time(),
        )

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        snap = await self._doc(session_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if data.get("user_id") and data["user_id"] != user_id:
            logger.warning("session %s user mismatch", session_id)
            return None

        events: list[Event] = []
        query = (
            self._doc(session_id).collection("adk_events").order_by("ts").limit(_MAX_EVENTS)
        )
        async for doc in query.stream():
            payload = (doc.to_dict() or {}).get("event")
            if not payload:
                continue
            try:
                events.append(Event.model_validate(payload))
            except Exception:  # tolerate schema drift across ADK versions
                logger.warning("skipping unparseable event %s in session %s", doc.id, session_id)

        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=data.get("state", {}),
            events=events,
            last_update_time=time.time(),
        )

    async def list_sessions(self, *, app_name: str, user_id: str) -> ListSessionsResponse:
        sessions: list[Session] = []
        query = self._db.collection("sessions").where("user_id", "==", user_id).limit(50)
        async for doc in query.stream():
            data = doc.to_dict() or {}
            sessions.append(
                Session(
                    id=doc.id, app_name=app_name, user_id=user_id,
                    state=data.get("state", {}), events=[], last_update_time=time.time(),
                )
            )
        return ListSessionsResponse(sessions=sessions)

    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        await self._doc(session_id).delete()

    async def append_event(self, session: Session, event: Event) -> Event:
        # Base impl applies event.actions.state_delta to session.state in memory.
        event = await super().append_event(session, event)
        try:
            doc = self._doc(session.id)
            await doc.collection("adk_events").add(
                {"ts": _now(), "event": event.model_dump(mode="json", exclude_none=True)}
            )
            await doc.set({"state": session.state, "updated_at": _now()}, merge=True)
        except Exception:
            logger.exception("failed to persist event for session %s", session.id)
        return event

    async def clear_state_keys(self, session_id: str, keys: list[str]) -> None:
        """Remove per-turn transient keys (citations, chart_spec) after they are emitted."""
        updates = {f"state.{k}": firestore.DELETE_FIELD for k in keys}
        try:
            await self._doc(session_id).update(updates)
        except Exception:
            logger.warning("clear_state_keys failed for session %s", session_id)

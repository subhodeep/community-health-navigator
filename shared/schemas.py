"""Single source of truth for cross-service payloads.

Imported by services/api, services/agent, services/worker.
The web client mirrors these shapes in web/src/types.js.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# SSE events (public /chat stream and internal agent /run stream — same shape)
# ---------------------------------------------------------------------------


class SSEEventName(str, Enum):
    token = "token"
    citations = "citations"
    chart_spec = "chart_spec"
    action_request = "action_request"
    done = "done"
    error = "error"


class TokenData(BaseModel):
    text: str


class CitationItem(BaseModel):
    n: int
    title: str
    uri: str = ""
    snippet: str = ""


class ChartSpecData(BaseModel):
    vega_lite: dict[str, Any]
    sql: Optional[str] = None


class ActionRequestData(BaseModel):
    intent: Literal["referral", "alert_subscription"]
    params: dict[str, Any]
    confirm_token: str


class DoneData(BaseModel):
    latency_ms: int
    agents_used: list[str] = Field(default_factory=list)


class ErrorData(BaseModel):
    message: str
    code: str = "internal"


class SSEEvent(BaseModel):
    """One JSON object per SSE `data:` line."""

    event: SSEEventName
    data: Any


# ---------------------------------------------------------------------------
# Action intents — Pub/Sub payloads published by the agent, executed by worker
# ---------------------------------------------------------------------------


class BaseIntent(BaseModel):
    intent_id: str
    user_id: str
    issued_at: str  # ISO-8601 UTC


class ReferralIntent(BaseIntent):
    type: Literal["referral"] = "referral"
    specialty: str
    facility_id: str = ""
    notes: str = ""


class AlertSubscriptionIntent(BaseIntent):
    type: Literal["alert_subscription"] = "alert_subscription"
    signal: Literal["aqi", "demand_anomaly"]
    threshold: float
    channel: Literal["email"] = "email"


def parse_intent(payload: dict[str, Any]) -> BaseIntent:
    """Parse a Pub/Sub intent payload into its typed model. Raises on unknown type."""
    kind = payload.get("type")
    if kind == "referral":
        return ReferralIntent.model_validate(payload)
    if kind == "alert_subscription":
        return AlertSubscriptionIntent.model_validate(payload)
    raise ValueError(f"unknown intent type: {kind!r}")


# ---------------------------------------------------------------------------
# Alert events — published by anomaly_scan function, fanned out by worker
# ---------------------------------------------------------------------------


class AlertEvent(BaseModel):
    signal: Literal["aqi", "demand_anomaly"]
    district: str
    date: str
    value: float
    detail: str = ""


# ---------------------------------------------------------------------------
# Internal API -> Agent contract
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    session_id: str
    user_id: str
    persona: Literal["citizen", "analyst"] = "citizen"
    message: str
    image_uri: Optional[str] = None  # gs:// URI of an uploaded image


class CreateSessionRequest(BaseModel):
    user_id: str
    persona: Literal["citizen", "analyst"] = "citizen"


class CreateSessionResponse(BaseModel):
    session_id: str

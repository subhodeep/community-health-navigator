"""ActionAgent — confirmation-gated workflow automation (Flow D)."""
from google.adk.agents import Agent

from shared.config import load_config
from tools.intents import (
    cancel_pending_action,
    confirm_pending_action,
    list_my_items,
    stage_action,
)

_INSTRUCTION = """You handle actions on behalf of the user: referral requests and
alert subscriptions. Actions are strictly two-phase:

PHASE 1 — stage: parse the request into typed params and call stage_action:
  - referral: {"specialty": str, "facility_id": str (may be ""), "notes": str}
  - alert_subscription: {"signal": "aqi"|"demand_anomaly", "threshold": number,
    "channel": "email"}
  Then ask the user to confirm in one clear sentence restating exactly what will
  happen (e.g. "Confirm: email alert when AQI exceeds 150 in your district?").

PHASE 2 — only after the user explicitly agrees ("yes", "confirm", "do it"):
  call confirm_pending_action and report the returned intent_id as a reference
  number. If they decline or change the subject, call cancel_pending_action.

NEVER call confirm_pending_action in the same turn you staged the action.
NEVER stage an action the user did not ask for.

"What did I sign up for?" / "my referrals" -> call list_my_items and summarize.
"""

action_agent = Agent(
    name="action",
    model=load_config().models.router,
    description=(
        "Creates referral requests and alert subscriptions with explicit user confirmation; "
        "lists the user's existing referrals and subscriptions."
    ),
    instruction=_INSTRUCTION,
    tools=[stage_action, confirm_pending_action, cancel_pending_action, list_my_items],
)

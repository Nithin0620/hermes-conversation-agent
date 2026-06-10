"""
tools/followup_tools.py
-----------------------
Hermes tool handler for scheduling deferred follow-up messages.

Registered tools:
  - schedule_followup  (toolset: real_estate)

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 8.1, 8.2
"""

import json
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------


def schedule_followup(
    conversation_id: str,
    account_id: int,
    delay_hours: int,
    note: str | None = None,
) -> str:
    """
    Schedule a follow-up message by inserting a row into hermes_followups.

    Preconditions:
      - conversation_id is a non-empty string.
      - account_id is a positive integer.
      - delay_hours will be clamped to [1, 720].
      - note is optional context for the follow-up message.

    Postconditions:
      - Inserts a row into hermes_followups with status='pending' and
        scheduled_at = UTC now + delay_hours.
      - Returns a valid JSON string with keys: followup_id, scheduled_at (ISO 8601).
      - On any exception: returns JSON with an "error" key; never raises.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 8.1, 8.2
    """
    # Late imports to avoid circular dependencies at module load time
    from services.state_store import _get_shared_store  # noqa: PLC0415
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    try:
        # Clamp delay_hours to [1, 720] — Requirements 4.2, 4.3
        delay_hours = max(1, min(int(delay_hours), 720))

        # Compute scheduled_at strictly in the future — Requirement 4.4
        now = datetime.now(timezone.utc)
        scheduled_at = now + timedelta(hours=delay_hours)
        scheduled_at_iso = scheduled_at.isoformat()

        store = _get_shared_store()
        followup_id = store.insert_followup(
            conversation_id=conversation_id,
            account_id=account_id,
            note=note,
            scheduled_at=scheduled_at_iso,
        )

        # Return followup_id and scheduled_at in ISO 8601 format — Requirement 4.5
        return json.dumps({"followup_id": followup_id, "scheduled_at": scheduled_at_iso})

    except Exception as exc:
        logger.exception("schedule_followup failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# JSON schema for Hermes tool registry
# ---------------------------------------------------------------------------

SCHEDULE_FOLLOWUP_SCHEMA = {
    "name": "schedule_followup",
    "description": "Schedule a follow-up message to be sent to the user after a delay.",
    "parameters": {
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": "Chatwoot conversation ID",
            },
            "account_id": {
                "type": "integer",
                "description": "Chatwoot account ID",
            },
            "delay_hours": {
                "type": "integer",
                "description": "Hours from now before sending the follow-up (1-720)",
                "minimum": 1,
                "maximum": 720,
            },
            "note": {
                "type": "string",
                "description": "Context for the follow-up message",
            },
        },
        "required": ["conversation_id", "account_id", "delay_hours"],
    },
}


# ---------------------------------------------------------------------------
# Tool registration — wrapped in try/except so the module loads even outside
# the Hermes runtime (e.g. during unit tests or standalone imports).
# ---------------------------------------------------------------------------

try:
    from tools.registry import registry  # noqa: PLC0415

    registry.register(
        name="schedule_followup",
        toolset="real_estate",
        handler=schedule_followup,
        schema=SCHEDULE_FOLLOWUP_SCHEMA,
    )
except ImportError:
    pass

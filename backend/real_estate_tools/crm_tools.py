"""
CRM tools for the Hermes real-estate agent.

Exposes three tool handlers:
  - assign_chatwoot_labels
  - create_lead
  - update_lead_stage

All handlers:
  - always return a JSON string (never raise)
  - are registered in the "real_estate" toolset via the Hermes tool registry
"""

import json
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid lead stages
# ---------------------------------------------------------------------------

VALID_STAGES = {"new_lead", "qualified_lead", "hot_lead", "warm_lead", "cold_lead"}

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def assign_chatwoot_labels(args: dict, **kwargs) -> str:
    """Assign CRM classification labels to a Chatwoot conversation.

    ``conversation_id`` is coerced to ``str`` because Groq sometimes passes it as integer.

    Creates any labels that do not yet exist in the account, then sets the
    conversation labels (capped at 6).

    Returns JSON: {"assigned": [...], "created": [...]}
    On error:     {"error": "<message>"}

    Preconditions:
      - account_id is a positive integer
      - conversation_id is a non-empty string
      - labels is a list of snake_case strings

    Postconditions:
      - At most 6 labels are assigned to the conversation
      - Labels not yet present in the account are created first
      - Returns a valid JSON string; never raises
    """
    account_id = args.get("account_id")
    conversation_id = args.get("conversation_id")
    labels = args.get("labels")
    conversation_id = str(conversation_id)
    try:
        from services.chatwoot import ChatwootClient  # late import – avoids circular deps

        client = ChatwootClient()

        # Fetch existing labels for the account — returns [(title, id), ...]
        existing = client.get_all_labels(account_id)
        existing_titles = {title for title, _ in existing}

        # Cap label list at 6 (requirement 3.1)
        labels_to_assign = labels[:6]

        # Determine which requested labels are missing and need to be created
        created = []
        for title in labels_to_assign:
            if title not in existing_titles:
                client.create_label(account_id, title)
                created.append(title)
                existing_titles.add(title)  # keep set consistent within the same call

        # Set conversation labels
        client.set_conversation_labels(account_id, conversation_id, labels_to_assign)

        return json.dumps({"assigned": labels_to_assign, "created": created})

    except Exception as exc:
        logger.exception("assign_chatwoot_labels failed: %s", exc)
        return json.dumps({"error": str(exc)})


def create_lead(args: dict, **kwargs) -> str:
    """Record or update a lead in the hermes_leads table.

    Uses an upsert so that calling this tool a second time for the same
    conversation_id updates the existing row instead of creating a duplicate
    (requirement 3.5).

    Returns JSON: {"lead_id": "<uuid>", "status": "created"}
    On error:     {"error": "<message>"}

    Preconditions:
      - account_id is a positive integer
      - conversation_id is a non-empty string
      - all other arguments are optional

    Postconditions:
      - A row exists in hermes_leads for conversation_id
      - Returns a valid JSON string; never raises
    """
    account_id = args.get("account_id")
    conversation_id = args.get("conversation_id")
    name = args.get("name")
    phone = args.get("phone")
    intent = args.get("intent")
    city = args.get("city")
    budget = args.get("budget")
    conversation_id = str(conversation_id)
    try:
        from services.state_store import _get_shared_store  # late import

        store = _get_shared_store()
        lead_id = store.upsert_lead(
            conversation_id=conversation_id,
            account_id=account_id,
            name=name,
            phone=phone,
            intent=intent,
            city=city,
            budget=budget,
        )

        return json.dumps({"lead_id": str(lead_id), "status": "created"})

    except Exception as exc:
        logger.exception("create_lead failed: %s", exc)
        return json.dumps({"error": str(exc)})


def update_lead_stage(args: dict, **kwargs) -> str:
    """Update the CRM stage of an existing lead.

    Stage validation is performed BEFORE any database call (requirement 3.7).

    Returns JSON: {"updated": true, "stage": "<stage>"}   on success
                  {"error": "Invalid stage: ..."}         on invalid stage
    On DB error:  {"error": "<message>"}

    Preconditions:
      - conversation_id is a non-empty string
      - stage is one of VALID_STAGES

    Postconditions:
      - hermes_leads row updated when stage is valid
      - Returns a valid JSON string; never raises
    """
    conversation_id = args.get("conversation_id")
    stage = args.get("stage")
    notes = args.get("notes")
    conversation_id = str(conversation_id)
    # Validate stage FIRST — before touching the database (requirement 3.7)
    if stage not in VALID_STAGES:
        sorted_stages = ", ".join(sorted(VALID_STAGES))
        return json.dumps(
            {"error": f"Invalid stage: {stage}. Must be one of: {sorted_stages}"}
        )

    try:
        from services.state_store import _get_shared_store  # late import

        store = _get_shared_store()
        store.update_lead_stage(
            conversation_id=conversation_id,
            stage=stage,
            notes=notes,
        )

        return json.dumps({"updated": True, "stage": stage})

    except Exception as exc:
        logger.exception("update_lead_stage failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# JSON schemas for Hermes tool registry
# ---------------------------------------------------------------------------

ASSIGN_CHATWOOT_LABELS_SCHEMA = {
    "name": "assign_chatwoot_labels",
    "description": (
        "Assign CRM classification labels to the Chatwoot conversation. "
        "Creates labels that do not yet exist."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "account_id":      {"type": "integer", "description": "Chatwoot account ID"},
            "conversation_id": {"type": "number",  "description": "Chatwoot conversation ID"},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of snake_case label strings (max 6)",
            },
        },
        "required": ["account_id", "conversation_id", "labels"],
    },
}

CREATE_LEAD_SCHEMA = {
    "name": "create_lead",
    "description": (
        "Record a new lead when meaningful contact information or buying intent is captured."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "account_id":      {"type": "integer", "description": "Chatwoot account ID"},
            "conversation_id": {"type": "number",  "description": "Chatwoot conversation ID"},
            "name":   {"type": "string", "description": "User name"},
            "phone":  {"type": "string", "description": "User phone"},
            "intent": {"type": "string", "description": "User intent"},
            "city":   {"type": "string", "description": "Preferred city"},
            "budget": {"type": "string", "description": "Budget range"},
        },
        "required": ["account_id", "conversation_id"],
    },
}

UPDATE_LEAD_STAGE_SCHEMA = {
    "name": "update_lead_stage",
    "description": "Update the CRM stage of an existing lead.",
    "parameters": {
        "type": "object",
        "properties": {
            "conversation_id": {"type": "number", "description": "Chatwoot conversation ID"},
            "stage": {
                "type": "string",
                "enum": ["new_lead", "qualified_lead", "hot_lead", "warm_lead", "cold_lead"],
            },
            "notes": {"type": "string", "description": "Optional notes"},
        },
        "required": ["conversation_id", "stage"],
    },
}

# ---------------------------------------------------------------------------
# Registration in the Hermes tool registry
# ---------------------------------------------------------------------------

try:
    from tools.registry import registry  # Hermes internal registry

    registry.register(
        name="assign_chatwoot_labels",
        toolset="real_estate",
        schema=ASSIGN_CHATWOOT_LABELS_SCHEMA,
        handler=assign_chatwoot_labels,
    )

    registry.register(
        name="create_lead",
        toolset="real_estate",
        schema=CREATE_LEAD_SCHEMA,
        handler=create_lead,
    )

    registry.register(
        name="update_lead_stage",
        toolset="real_estate",
        schema=UPDATE_LEAD_STAGE_SCHEMA,
        handler=update_lead_stage,
    )

except ImportError:
    # hermes-agent is not installed in the current environment (e.g. during testing)
    logger.debug("tools.registry not available — skipping CRM tool registration")

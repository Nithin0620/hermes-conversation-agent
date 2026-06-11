import os
import logging
from flask import Blueprint, request, jsonify
from debug_trace import BUILD_MARKER, dbg
from services.chatwoot import ChatwootClient
from services.state_store import StateStore
from services.hermes_agent import HermesAgentService

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("webhook", __name__)
chatwoot = ChatwootClient()
store = StateStore()
hermes_service = HermesAgentService(
    state_store=store,
    model=os.getenv("HERMES_MODEL", "llama-3.3-70b-versatile"),
    api_key=os.getenv("GROQ_API_KEY"),
    base_url=os.getenv("HERMES_BASE_URL", "https://api.groq.com/openai/v1"),
)


@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    event = data.get("event")
    message_type = data.get("message_type")

    # #region agent log
    dbg(
        "webhook.py:entry",
        "Webhook POST received",
        {
            "build_marker": BUILD_MARKER,
            "event": event,
            "message_type": message_type,
            "content_len": len(str(data.get("content", ""))),
        },
        hypothesis_id="H1,H5",
    )
    # #endregion

    logger.info("[Webhook] Received: event=%s message_type=%s content=%s", event, message_type, str(data.get("content", ""))[:60])

    if event != "message_created" or message_type != "incoming":
        # #region agent log
        dbg(
            "webhook.py:ignored",
            "Webhook event ignored",
            {"event": event, "message_type": message_type},
            hypothesis_id="H5",
        )
        # #endregion
        logger.info("[Webhook] IGNORED — event=%s message_type=%s", event, message_type)
        return jsonify({"status": "ignored"})

    account_id = data["account"]["id"]
    conversation_id = str(data["conversation"]["id"])
    user_message = data["content"]

    logger.info("[Webhook] conv=%s user=%s", conversation_id, user_message[:80])

    history = store.get_history(conversation_id)
    is_first_reply = len(history) == 0

    reply = hermes_service.run(conversation_id, user_message, account_id)

    prefix = "🏦 *Hermes - Banksauctions.com*\n\n"
    full_reply = (prefix + reply) if is_first_reply else reply

    # #region agent log
    dbg(
        "webhook.py:reply",
        "Webhook sending reply to Chatwoot",
        {
            "conversation_id": conversation_id,
            "reply_len": len(reply),
            "reply_is_fallback": reply == "I'm here to help. What are you looking for?",
            "is_first_reply": is_first_reply,
        },
        hypothesis_id="H2",
    )
    # #endregion

    logger.info("[Webhook] conv=%s reply=%s...", conversation_id, reply[:100])
    chatwoot.send_message(account_id, conversation_id, full_reply)

    # Label update disabled to conserve Groq TPM (12k/min limit).
    # Re-enable after upgrading to a higher-tier Groq plan.
    # try:
    #     hermes_service.run_label_update(conversation_id, account_id)
    # except Exception as exc:
    #     logger.warning("[Webhook] Label update error for conv=%s: %s", conversation_id, exc)

    return jsonify({"status": "success"})

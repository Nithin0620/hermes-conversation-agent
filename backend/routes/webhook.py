import os
import logging
from flask import Blueprint, request, jsonify
from services.chatwoot import ChatwootClient
from services.state_store import StateStore
from services.hermes_agent import HermesAgentService

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("webhook", __name__)
chatwoot = ChatwootClient()
store = StateStore()
hermes_service = HermesAgentService(
    state_store=store,
    model=os.getenv("HERMES_MODEL", "groq/llama-3.3-70b-versatile"),
    api_key=os.getenv("GROQ_API_KEY"),
    base_url=os.getenv("HERMES_BASE_URL", "https://api.groq.com/openai/v1"),
)


@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    logger.info("[Webhook] Received: event=%s message_type=%s", data.get("event"), data.get("message_type"))

    event = data.get("event")
    message_type = data.get("message_type")

    if event != "message_created" or message_type != "incoming":
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

    logger.info("[Webhook] conv=%s reply=%s...", conversation_id, reply[:100])
    chatwoot.send_message(account_id, conversation_id, full_reply)

    try:
        hermes_service.run_label_update(conversation_id, account_id)
    except Exception as exc:
        logger.warning("[Webhook] Label update error for conv=%s: %s", conversation_id, exc)

    return jsonify({"status": "success"})

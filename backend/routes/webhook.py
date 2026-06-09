from flask import Blueprint, request, jsonify
from services.llm import LLMService
from services.chatwoot import ChatwootClient

webhook_bp = Blueprint("webhook", __name__)
llm = LLMService()
chatwoot = ChatwootClient()


@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    print("[Webhook] Received:", data.get("event"), data.get("message_type"))

    event = data.get("event")
    message_type = data.get("message_type")

    # Ignore non-incoming messages (prevents infinite loops)
    if event != "message_created" or message_type != "incoming":
        return jsonify({"status": "ignored"})

    account_id = data["account"]["id"]
    conversation_id = data["conversation"]["id"]
    user_message = data["content"]

    print(f"[Webhook] User said: {user_message}")

    reply = llm.ask(
        f"You are Hermes, a helpful AI assistant for Banksauctions.com. "
        f"Keep responses concise and friendly. User says: {user_message}"
    )

    print(f"[Webhook] LLM reply: {reply}")
    chatwoot.send_message(account_id, conversation_id, reply)

    return jsonify({"status": "success"})

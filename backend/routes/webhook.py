from flask import Blueprint, request, jsonify
from services.llm import LLMService
from services.chatwoot import ChatwootClient
from services.database import DatabaseService
from services.state_store import StateStore

webhook_bp = Blueprint("webhook", __name__)
llm = LLMService()
chatwoot = ChatwootClient()
db = DatabaseService()
store = StateStore()

DEFAULT_STATE = {
    "results": [],
    "total": 0,
    "offset": 0,
    "last_filters": {},
}


def get_filter_hints():
    try:
        cities = db.get_distinct_values("city")
        types = db.get_distinct_values("asset_type")
    except Exception:
        cities = []
        types = []
    return cities, types


def load_state(conversation_id):
    saved = store.load_state(conversation_id)
    if saved:
        return {**DEFAULT_STATE, **saved}
    return dict(DEFAULT_STATE)


@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    print("[Webhook] Received:", data.get("event"), data.get("message_type"))

    event = data.get("event")
    message_type = data.get("message_type")

    if event != "message_created" or message_type != "incoming":
        return jsonify({"status": "ignored"})

    account_id = data["account"]["id"]
    conversation_id = data["conversation"]["id"]
    user_message = data["content"]

    print(f"[Webhook] User said: {user_message}")

    state = load_state(conversation_id)
    store.add_message(conversation_id, "user", user_message)

    try:
        reply = handle_conversation(conversation_id, user_message, state)
    except Exception as e:
        print(f"[Webhook] Error: {e}")
        reply = "Sorry, I encountered an error. Please try again."

    store.add_message(conversation_id, "assistant", reply)
    store.save_state(conversation_id, state)

    print(f"[Webhook] Reply: {reply[:100]}...")
    chatwoot.send_message(account_id, conversation_id, reply)

    try:
        update_labels(account_id, conversation_id)
    except Exception as e:
        print(f"[Webhook] Label update error: {e}")

    return jsonify({"status": "success"})


def update_labels(account_id, conversation_id):
    existing = chatwoot.get_conversation_labels(account_id, conversation_id)
    history = store.get_history(conversation_id)
    cities, types = get_filter_hints()
    all_labels = chatwoot.get_all_labels(account_id)

    suggested = llm.suggest_labels(history, all_labels, cities, types)
    if not suggested:
        return

    to_create = [l for l in suggested if l not in all_labels]
    for label in to_create:
        chatwoot.create_label(account_id, label)

    chatwoot.set_conversation_labels(account_id, conversation_id, suggested)


def handle_conversation(conversation_id, user_message, state):
    msg = user_message.strip().lower()

    if state["results"] and msg in ("more", "next", "more please", "show more"):
        offset = state["offset"] + 5
        if offset >= state["total"]:
            return "That's all the results I have! Would you like to try a different search?"

        try:
            last_filters = state.get("last_filters", {})
            properties, _ = db.search_auctions(filters=last_filters, limit=5, offset=offset)
            state["results"].extend(properties)
            state["offset"] = offset

            reply_parts = [f"Here are {len(properties)} more properties:"]
            for i, p in enumerate(properties, offset + 1):
                reply_parts.append(f"{i}. {db.format_auction_brief(p)}")

            remaining = state["total"] - (offset + 5)
            if remaining > 0:
                reply_parts.append(f"\n{remaining} more available. Reply *more* to see them.")

            return "\n\n".join(reply_parts)
        except Exception as e:
            print(f"[More Error] {e}")
            return "Sorry, couldn't load more results right now."

    if state["results"] and msg.isdigit():
        idx = int(msg) - 1
        if 0 <= idx < len(state["results"]):
            detail = db.format_auction_detail(state["results"][idx])
            return f"*Property #{msg} Details:*\n\n{detail}"
        else:
            return f"Please pick a number between 1 and {len(state['results'])}."

    cities, types = get_filter_hints()

    decision = llm.decide_action(
        user_message=user_message,
        conversation_history=store.get_history(conversation_id),
        available_cities=cities,
        available_types=types,
    )

    action = decision.get("action", "respond")
    filters = decision.get("filters", {})

    print(f"[Decide] action={action}, filters={filters}")

    if action == "ask":
        return decision.get("message", "Could you tell me more about what you're looking for?")

    if action == "search":
        try:
            properties, total = db.search_auctions(filters=filters, limit=5)
            state["results"] = properties
            state["total"] = total
            state["offset"] = 0
            state["last_filters"] = filters

            if total == 0:
                return llm.generate_property_response([], total, filters)

            reply = llm.generate_property_response(properties, total, filters)
            if total > 5:
                reply += f"\n\n_{total - 5} more properties available. Reply 'more' to see them or type a number for details._"

            return reply
        except Exception as e:
            print(f"[Search Error] {e}")
            return "Sorry, I couldn't search the database right now. Please try again later."

    return decision.get("message", "Hello! I can help you find bank auction properties. Which city are you interested in?")

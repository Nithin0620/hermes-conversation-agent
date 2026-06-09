import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import requests

load_dotenv()

app = Flask(__name__)

CHATWOOT_API_URL = os.getenv("CHATWOOT_API_URL")
CHATWOOT_ACCESS_TOKEN = os.getenv("CHATWOOT_ACCESS_TOKEN")


def send_reply(account_id, conversation_id, message):
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {
        "api_access_token": CHATWOOT_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    body = {"content": message}
    resp = requests.post(url, headers=headers, json=body)
    print(f"Reply sent: {resp.status_code}")


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    print("Received from Chatwoot:")
    print(data)

    if data.get("event") == "message_created" and data.get("message_type") == "incoming":
        account_id = data["account"]["id"]
        conversation_id = data["conversation"]["id"]
        user_message = data["content"]

        reply_text = f"You said: {user_message}"
        send_reply(account_id, conversation_id, reply_text)

    return jsonify({"status": "success"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

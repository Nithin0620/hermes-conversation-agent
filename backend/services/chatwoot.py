import os
import requests


class ChatwootClient:
    def __init__(self):
        self.api_url = os.getenv("CHATWOOT_API_URL")
        self.access_token = os.getenv("CHATWOOT_ACCESS_TOKEN")

    def send_message(self, account_id, conversation_id, content):
        url = f"{self.api_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        headers = {
            "api_access_token": self.access_token,
            "Content-Type": "application/json",
        }
        body = {"content": content}
        resp = requests.post(url, headers=headers, json=body)
        print(f"[Chatwoot] Reply sent: {resp.status_code}")
        return resp

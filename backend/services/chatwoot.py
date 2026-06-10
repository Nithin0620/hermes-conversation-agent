import os
import requests


class ChatwootClient:
    def __init__(self):
        self.api_url = os.getenv("CHATWOOT_API_URL")
        self.access_token = os.getenv("CHATWOOT_ACCESS_TOKEN")
        self._headers = {
            "api_access_token": self.access_token,
            "Content-Type": "application/json",
        }

    def send_message(self, account_id, conversation_id, content):
        url = f"{self.api_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        body = {"content": content}
        resp = requests.post(url, headers=self._headers, json=body)
        print(f"[Chatwoot] Reply sent: {resp.status_code}")
        return resp

    def get_conversation_labels(self, account_id, conversation_id):
        url = f"{self.api_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/labels"
        resp = requests.get(url, headers=self._headers)
        if resp.ok:
            return resp.json().get("payload", [])
        return []

    def set_conversation_labels(self, account_id, conversation_id, labels):
        url = f"{self.api_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/labels"
        body = {"labels": labels}
        resp = requests.put(url, headers=self._headers, json=body)
        print(f"[Chatwoot] Labels set ({labels}): {resp.status_code}")
        return resp

    def get_all_labels(self, account_id):
        url = f"{self.api_url}/api/v1/accounts/{account_id}/labels"
        resp = requests.get(url, headers=self._headers)
        if resp.ok:
            return [l["title"] for l in resp.json().get("payload", [])]
        return []

    def create_label(self, account_id, title, color="#00FF00", description=""):
        url = f"{self.api_url}/api/v1/accounts/{account_id}/labels"
        body = {
            "title": title,
            "color": color,
            "description": description,
        }
        resp = requests.post(url, headers=self._headers, json=body)
        print(f"[Chatwoot] Label created ({title}): {resp.status_code}")
        return resp

import os
from google import genai


class LLMService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.0-flash"

    def ask(self, prompt):
        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return resp.text

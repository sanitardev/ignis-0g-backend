import json
from collections.abc import Sequence
from urllib.parse import urlsplit

from app.ai.providers import JsonAPI, Message, ProviderUnavailable


class RemoteLLM:
    def __init__(self, api: JsonAPI, model: str, max_output_tokens: int):
        self.api = api
        self.model = model
        self.max_output_tokens = max_output_tokens

    async def generate(self, messages: Sequence[Message]) -> object:
        if not self.model:
            raise ProviderUnavailable("Chat model is missing")
        payload = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": self.max_output_tokens,
            "temperature": 0.2,
        }
        if urlsplit(self.api.base_url).hostname == "openrouter.ai":
            payload["reasoning"] = {"enabled": False}
            payload["response_format"] = {"type": "json_object"}
        response = await self.api.post("/chat/completions", payload)
        try:
            choice = response["choices"][0]
            if choice["finish_reason"] == "length":
                raise ProviderUnavailable("Chat response exceeded the output token limit")
            if choice["finish_reason"] not in {"stop", "end_turn"}:
                return None
            content = choice["message"]["content"].strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()
            return json.loads(content)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            return None

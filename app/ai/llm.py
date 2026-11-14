import json
from collections.abc import Sequence

from app.ai.providers import JsonAPI, Message, ProviderUnavailable


class RemoteLLM:
    def __init__(self, api: JsonAPI, model: str):
        self.api = api
        self.model = model

    async def generate(self, messages: Sequence[Message]) -> object:
        if not self.model:
            raise ProviderUnavailable("Chat model is missing")
        response = await self.api.post("/chat/completions", {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": 1200,
            "temperature": 0.2,
        })
        try:
            choice = response["choices"][0]
            if choice["finish_reason"] not in {"stop", "end_turn"}:
                return None
            content = choice["message"]["content"].strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()
            return json.loads(content)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            return None

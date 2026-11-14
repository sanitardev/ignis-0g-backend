import json
import logging
from collections.abc import Sequence

from app.ai.providers import JsonAPI, Message, ProviderUnavailable

logger = logging.getLogger("uvicorn.error.rag")


class RemoteLLM:
    def __init__(self, api: JsonAPI, model: str):
        self.api = api
        self.model = model

    async def generate(self, messages: Sequence[Message]) -> object:
        if not self.model:
            raise ProviderUnavailable("Chat model is missing")
        payload = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": 2400,
            "temperature": 0.2,
        }
        if self.api.base_url == "https://openrouter.ai/api/v1":
            payload.update(
                max_tokens=1200,
                response_format={"type": "json_object"},
                provider={"sort": "latency", "require_parameters": True},
            )
            if self.model.startswith("deepseek/deepseek-v4"):
                payload["reasoning"] = {"enabled": False}
        response = await self.api.post("/chat/completions", payload)
        try:
            choice = response["choices"][0]
            if choice["finish_reason"] not in {"stop", "end_turn"}:
                logger.info("rag stage=generation outcome=%s", "token_limit" if choice["finish_reason"] == "length" else "incomplete_completion")
                return None
            content = choice["message"]["content"].strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()
            return json.loads(content)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            logger.info("rag stage=generation outcome=invalid_completion_json")
            return None

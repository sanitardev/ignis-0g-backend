import asyncio
import json
import os

import httpx

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"
_generation_slots = asyncio.Semaphore(2)


class ProviderUnavailable(Exception):
    pass


class ProviderTimeout(Exception):
    pass


async def generate(messages: list[dict[str, str]]) -> object:
    key = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY")
    if not key:
        raise ProviderUnavailable
    payload = {
        "model": os.getenv("LLM_MODEL") or DEFAULT_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 1600,
        "temperature": 0.2,
    }
    try:
        async with asyncio.timeout(7):
            async with _generation_slots, httpx.AsyncClient(timeout=7, trust_env=False) as client:
                response = await client.post(
                    ENDPOINT, headers={"Authorization": f"Bearer {key}"}, json=payload
                )
                response.raise_for_status()
    except (TimeoutError, httpx.TimeoutException):
        raise ProviderTimeout from None
    except httpx.HTTPError:
        raise ProviderUnavailable from None

    try:
        choice = response.json()["choices"][0]
        if choice["finish_reason"] != "stop":
            return None
        return json.loads(choice["message"]["content"])
    except (ValueError, KeyError, TypeError, IndexError):
        return None

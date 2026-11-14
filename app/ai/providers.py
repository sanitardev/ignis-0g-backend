from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from app.ai.retrieval import Evidence

Message = dict[str, str]


class ProviderUnavailable(Exception):
    pass


class ProviderTimeout(ProviderUnavailable):
    pass


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...
    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...
    async def embed_query(self, query: str) -> Sequence[float]: ...


class RerankerProvider(Protocol):
    async def rerank(self, query: str, documents: Sequence[Evidence]) -> Sequence[int]:
        """Return zero-based positions in descending relevance order."""
        ...


class LLMProvider(Protocol):
    async def generate(self, messages: Sequence[Message]) -> object: ...


class JsonAPI:
    def __init__(self, client: httpx.AsyncClient, base_url: str, key: str, timeout: float, retries: int):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout
        self.retries = retries

    async def post(self, path: str, payload: dict) -> dict:
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or not self.key:
            raise ProviderUnavailable("Missing or invalid provider configuration")

        for attempt in range(self.retries + 1):
            try:
                async with asyncio.timeout(self.timeout):
                    response = await self.client.post(
                        self.base_url + path,
                        headers={"Authorization": f"Bearer {self.key}"},
                        json=payload, timeout=self.timeout, follow_redirects=False,
                    )
            except (TimeoutError, httpx.TimeoutException):
                failure = ProviderTimeout
            except httpx.TransportError:
                failure = ProviderUnavailable
            else:
                if response.is_success:
                    try:
                        data = response.json()
                    except ValueError:
                        raise ProviderUnavailable("Invalid provider response") from None
                    if not isinstance(data, dict):
                        raise ProviderUnavailable("Invalid provider response")
                    return data

                failure = ProviderUnavailable
                if response.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise failure(f"Provider returned HTTP {response.status_code}")
                if response.status_code in {408, 504}:
                    failure = ProviderTimeout

            if attempt == self.retries:
                raise failure("Provider request failed") from None
            await asyncio.sleep(0.15 * (2 ** attempt))
        raise ProviderUnavailable

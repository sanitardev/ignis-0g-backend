from contextlib import asynccontextmanager
from os import getenv

import httpx

from app.ai.embeddings import RemoteEmbedding
from app.ai.llm import RemoteLLM
from app.ai.providers import JsonAPI
from app.ai.reranking import RemoteReranker
from app.ai.settings import RagSettings


@asynccontextmanager
async def configured_providers(settings: RagSettings):
    async with httpx.AsyncClient(trust_env=False) as client:
        base_url = getenv("LLM_BASE_URL", "https://ts.ree.kz/api/ai/v1")
        key = getenv("LLM_API_KEY", "")
        llm = RemoteLLM(
            JsonAPI(client, base_url, key, settings.timeout, settings.retries),
            getenv("LLM_MODEL", "anthropic/claude-haiku-5-5"),
        )
        embedding_url = getenv("EMBEDDING_BASE_URL")
        embedding_key = getenv("EMBEDDING_API_KEY") or (key if not embedding_url else "")
        embedding = RemoteEmbedding(
            JsonAPI(client, embedding_url or base_url, embedding_key, settings.timeout, settings.retries),
            getenv("EMBEDDING_MODEL", ""),
            send_dimensions=getenv("EMBEDDING_SEND_DIMENSIONS", "true").lower() == "true",
        )
        reranker = None
        if model := getenv("RERANKER_MODEL"):
            reranker_url = getenv("RERANKER_BASE_URL")
            reranker_key = getenv("RERANKER_API_KEY") or (key if not reranker_url else "")
            reranker = RemoteReranker(
                JsonAPI(client, reranker_url or base_url, reranker_key, settings.timeout, 0), model
            )
        yield embedding, reranker, llm

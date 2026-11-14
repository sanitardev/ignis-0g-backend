from collections.abc import Sequence

from app.ai.providers import JsonAPI, ProviderUnavailable
from app.ai.retrieval import Evidence


class RemoteReranker:
    def __init__(self, api: JsonAPI, model: str):
        self.api = api
        self.model = model

    async def rerank(self, query: str, documents: Sequence[Evidence]) -> list[int]:
        response = await self.api.post("/rerank", {
            "model": self.model,
            "query": query,
            "documents": [
                "\n".join(filter(None, (item.study_slug, item.title, item.locator, item.excerpt)))
                for item in documents
            ],
            "top_n": len(documents),
        })
        try:
            return [item["index"] for item in response["results"]]
        except (KeyError, TypeError):
            raise ProviderUnavailable("Invalid reranker response") from None

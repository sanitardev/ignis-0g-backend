import json
import math
from collections.abc import Sequence

from app.ai.providers import JsonAPI, ProviderUnavailable

DIMENSION = 384


def vector_parameter(vector: Sequence[float]) -> str:
    if len(vector) != DIMENSION or any(
        type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 3e38
        for value in vector
    ) or not any(vector):
        raise ProviderUnavailable(f"Expected a nonzero {DIMENSION}-dimensional embedding")
    return json.dumps(list(vector), allow_nan=False)


class RemoteEmbedding:
    def __init__(self, api: JsonAPI, model: str, *, send_dimensions: bool):
        self.api = api
        self.model = model
        self.send_dimensions = send_dimensions

    @property
    def model_id(self) -> str:
        return f"{self.api.base_url}:{self.model}:{DIMENSION}"

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.model:
            raise ProviderUnavailable("Embedding model is missing")
        payload = {"model": self.model, "input": list(texts)}
        if self.send_dimensions:
            payload["dimensions"] = DIMENSION
        response = await self.api.post("/embeddings", payload)
        try:
            rows = sorted(response["data"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError
            vectors = [row["embedding"] for row in rows]
            if not all(isinstance(vector, list) for vector in vectors):
                raise ValueError
            return vectors
        except (KeyError, TypeError, ValueError):
            raise ProviderUnavailable("Invalid embedding response") from None

    async def embed_query(self, query: str) -> list[float]:
        vector, = await self.embed_documents([query])
        return vector

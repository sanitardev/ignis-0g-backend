from app.ai.embeddings import DIMENSION


class MockEmbedding:
    model_id = f"mock-{DIMENSION}"
    vector = [1.0] + [0.0] * (DIMENSION - 1)

    def __init__(self):
        self.batches = []
        self.queries = []

    async def embed_documents(self, texts):
        self.batches.append(list(texts))
        return [self.vector for _ in texts]

    async def embed_query(self, query):
        self.queries.append(query)
        return self.vector


class MockReranker:
    def __init__(self, result):
        self.result = result

    async def rerank(self, query, documents):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class MockLLM:
    def __init__(self, responses):
        self.responses = responses
        self.messages = []

    async def generate(self, messages):
        self.messages.append(messages)
        return self.responses.pop(0)

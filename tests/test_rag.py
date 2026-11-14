import asyncio
from uuid import uuid4

import pytest

from app.ai.embeddings import DIMENSION
from app.ai.ingestion import document_chunks, tokenizer
from app.ai.providers import ProviderUnavailable
from app.ai.retrieval import Evidence
from app.ai.service import RagService
from app.ai.settings import RagSettings
from app.schemas.assistant import ChatRequest


def test_sections_pages_and_token_limits():
    settings = RagSettings(chunk_tokens=40, chunk_overlap=8)
    text = "---\nid: 42\n---\n# Study\n## Methods\n" + "A sentence about material. " * 100
    text += "\f## Results\nA result."
    chunks = list(document_chunks(text, settings))
    assert len(chunks) > 2
    assert chunks[0].section == "Study / Methods"
    assert chunks[-1].page == 2
    assert chunks[-1].section == "Results"
    assert all("id: 42" not in chunk.content for chunk in chunks)
    assert all(len(tokenizer().encode_ordinary(chunk.content)) <= 40 for chunk in chunks)


def test_rerank_fallback_and_reject_citations():
    from tests.rag_mocks import MockEmbedding, MockLLM, MockReranker

    documents = [
        Evidence(uuid4(), uuid4(), "flex", "Report", "https://example.org", f"Excerpt {i}", None)
        for i in range(7)
    ]

    class Repository:
        async def has_chunks(self, request, revision):
            return True

        async def search(self, request, vector, revision, limit):
            assert limit == 20
            return documents

    async def run():
        llm = MockLLM([{"query": "Standalone"}, {"answer": "Supported [1].", "citation_indices": [1]}])
        embedding = MockEmbedding()
        reranker = MockReranker(ProviderUnavailable())
        rag = RagService(embedding, reranker, llm, RagSettings(), Repository())
        request = ChatRequest(message="What about it?", history=[{"role":"user","content":"FLEX"}])
        answer = await rag.ask(request)
        assert embedding.queries == ["Standalone"]
        assert answer.citations[0].chunk_id == documents[0].chunk_id
        assert "Excerpt 4" in llm.messages[-1][-1]["content"]
        assert "Excerpt 5" not in llm.messages[-1][-1]["content"]

        llm.responses.extend([{"query": "Standalone"}, {"answer": "Invented [7].", "citation_indices": [7]}])
        assert (await rag.ask(request)).status == "insufficient_evidence"

        reranker.result = [6, 5]
        llm.responses.extend([{"query": "Standalone"}, {"answer": "Reranked [1].", "citation_indices": [1]}])
        assert (await rag.ask(request)).citations[0].chunk_id == documents[6].chunk_id

    asyncio.run(run())


def test_provider_retries_and_does_not_retry_authentication():
    import httpx
    from app.ai.providers import JsonAPI

    async def run():
        statuses = iter([503, 200, 401])
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(next(statuses), json={"ok": True})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            api = JsonAPI(client, "https://example.test/v1", "mock-key", 1, 1)
            assert await api.post("/chat/completions", {}) == {"ok": True}
            with pytest.raises(ProviderUnavailable, match="401"):
                await api.post("/chat/completions", {})
            assert len(calls) == 3

    asyncio.run(run())


def test_reindex_on_model_change_and_keep_old_index_when_provider_fails(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.ai import ingestion, retrieval
    from app.core.database import engine
    from app.schemas.ingestion import Package
    from app.services.ingestion import import_package
    from tests.rag_mocks import MockEmbedding, MockLLM

    async def run():
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            monkeypatch.setattr(ingestion, "session_factory", factory)
            monkeypatch.setattr(retrieval, "session_factory", factory)
            settings = RagSettings(batch_size=1)
            original = MockEmbedding()
            llm = MockLLM([{"answer": "Supported [1].", "citation_indices": [1]}] * 3)
            repository = retrieval.PgVectorRepository()
            rag = RagService(original, None, llm, settings, repository)
            request = ChatRequest(message="What was reported?", study_id="rag-one")
            raw = {"schema_version": 1, "studies": [
                {
                    "slug": f"rag-{suffix}", "title": "Synthetic",
                    "description": "Test data", "category": "test",
                    "sources": [{
                        "source_key": "example", "title": f"Report {suffix}",
                        "url": "https://example.org/report", "source_type": "report",
                        "text_content": f"# Results\nSynthetic excerpt {suffix}",
                    }],
                } for suffix in ("one", "two")
            ]}
            try:
                await import_package(Package.model_validate(raw), factory=factory)
                assert await ingestion.index_sources(original, settings) == 2
                assert len(original.batches) == 2
                assert await ingestion.index_sources(original, settings) == 0
                first = await rag.ask(request)
                assert first.related_study_ids == ["rag-one"]
                assert first.citations[0].locator == "Results"
                assert first.citations[0].excerpt == "Synthetic excerpt one"

                replacement = MockEmbedding()
                replacement.model_id = "new-embedding-model"
                replacement.vector = [1.0]
                with pytest.raises(ProviderUnavailable, match=f"{DIMENSION}-dimensional"):
                    await ingestion.index_sources(replacement, settings)
                assert (await rag.ask(request)).citations == first.citations

                replacement.vector = original.vector
                assert await ingestion.index_sources(replacement, settings) == 2
                assert (await rag.ask(request)).status == "insufficient_evidence"
                updated = await RagService(replacement, None, llm, settings, repository).ask(request)
                assert updated.citations[0].chunk_id != first.citations[0].chunk_id

                raw["studies"][0]["sources"][0]["text_content"] = None
                await import_package(Package.model_validate(raw), factory=factory)
                assert await ingestion.index_sources(replacement, settings) == 1
                assert await ingestion.index_sources(replacement, settings) == 0
            finally:
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(run())


def test_embedding_adapter_orders_batch_response_and_requests_schema_dimension():
    import json

    import httpx

    from app.ai.embeddings import DIMENSION, RemoteEmbedding, vector_parameter
    from app.ai.providers import JsonAPI

    async def run():
        def respond(request):
            payload = json.loads(request.content)
            assert request.url.path == "/v1/embeddings"
            assert payload["dimensions"] == DIMENSION
            return httpx.Response(200, json={"data": [
                {"index": index, "embedding": [index + 1.0] + [0.0] * (DIMENSION - 1)}
                for index in reversed(range(len(payload["input"])))
            ]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = RemoteEmbedding(
                JsonAPI(client, "https://example.test/v1", "mock-key", 1, 0),
                "remote-mock", send_dimensions=True,
            )
            first, second = await adapter.embed_documents(["one", "two"])
            assert json.loads(vector_parameter(first))[0] == 1
            assert json.loads(vector_parameter(second))[0] == 2

    asyncio.run(run())

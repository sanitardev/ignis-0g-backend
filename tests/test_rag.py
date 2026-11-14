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
        llm = MockLLM([{"query": "Standalone"}, {"status": "answered", "answer": "Supported [1].", "citation_indices": [1]}])
        embedding = MockEmbedding()
        reranker = MockReranker(ProviderUnavailable())
        rag = RagService(embedding, reranker, llm, RagSettings(), Repository())
        request = ChatRequest(message="What about it?", history=[{"role":"user","content":"FLEX"}])
        answer = await rag.ask(request)
        assert embedding.queries == ["Standalone"]
        assert answer.citations[0].chunk_id == documents[0].chunk_id
        assert "Excerpt 4" in llm.messages[-1][-1]["content"]
        assert "Excerpt 5" not in llm.messages[-1][-1]["content"]

        llm.responses.extend([{"query": "Standalone"}, {"status": "answered", "answer": "Invented [7].", "citation_indices": [7]}])
        assert (await rag.ask(request)).status == "insufficient_evidence"

        reranker.result = [6, 5]
        llm.responses.extend([{"query": "Standalone"}, {"status": "answered", "answer": "Reranked [1].", "citation_indices": [1]}])
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
            class DistinctEmbedding(MockEmbedding):
                async def embed_documents(self, texts):
                    vectors = await super().embed_documents(texts)
                    return [
                        vector if passage.endswith("one") else [0.0, *vector[:-1]]
                        for passage, vector in zip(texts, vectors, strict=True)
                    ]

            original = DistinctEmbedding()
            llm = MockLLM([{"status": "answered", "answer": "Supported [1].", "citation_indices": [1]}] * 3)
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
                from app.ai.embeddings import vector_parameter

                vector = vector_parameter(original.vector)
                revision = ingestion.index_revision(original, settings)
                global_query = ChatRequest(message="Results", scope="global", study_id="rag-two")
                matches = await repository.search(global_query, vector, revision, 2)
                assert [item.study_slug for item in matches] == ["rag-one", "rag-two"]
                scoped_query = ChatRequest(message="Results", study_id="rag-two")
                matches = await repository.search(scoped_query, vector, revision, 2)
                assert [item.study_slug for item in matches] == ["rag-two"]

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


def test_inline_citations_determine_response_order():
    from uuid import uuid4
    from app.ai.retrieval import Evidence
    from app.ai.service import validate_answer

    evidence = [
        Evidence(uuid4(), uuid4(), 'demo', 'Test', 'https://example.org', 'Example', None)
        for _ in range(2)
    ]
    response = validate_answer({"status": "answered", "answer": "Second [2]. First [1]. Second again [2].", "citation_indices": [1]}, evidence, "Question")
    assert response.answer == "Second [1]. First [2]. Second again [1]."
    assert [item.chunk_id for item in response.citations] == [evidence[1].chunk_id, evidence[0].chunk_id]
    for answer in ("No inline source.", "Invalid [3].", "Mixed [1][0]."):
        assert validate_answer({"status": "answered", "answer": answer}, evidence, "Question").status == "insufficient_evidence"


def test_global_context_prioritizes_multiple_studies():
    from uuid import uuid4
    from app.ai.retrieval import Evidence
    from app.ai.service import select_context

    rows = [
        Evidence(uuid4(), uuid4(), slug, 'Test', 'https://example.org', str(index), None)
        for index, slug in enumerate(('flex', 'flex', 'acme', 'saffire'))
    ]
    assert select_context(rows, 3, diversify=True) == [rows[0], rows[2], rows[3]]
    assert select_context(rows, 3, diversify=False) == rows[:3]


def test_context_skips_duplicate_passages_and_uses_distinct_sections():
    from app.ai.service import select_context

    def item(study, excerpt, locator):
        return Evidence(uuid4(), uuid4(), study, study, "https://example.org", excerpt, locator)

    results = [
        item("flex", "Reported result", "Results"),
        item("flex", "reported  result", "Results"),
        item("bass", "Reported result", "Results"),
        item("flex", "Test conditions", "Methods"),
    ]
    assert select_context(results, limit=3) == [results[0], results[2], results[3]]


@pytest.mark.parametrize("answer,indices", [
    ("Claim without a citation.", [1]),
    ("Claim [1], other claim [9].", [1]),
    ("Claim [1](https://example.org/forged).", [1]),
])
def test_citations_reject_missing_invalid_or_linked_markers(answer, indices):
    from app.ai.service import validate_answer

    evidence = [
        Evidence(uuid4(), uuid4(), "flex", f"Report {index}", "https://example.org", "Excerpt", None)
        for index in range(2)
    ]
    response = validate_answer({"status": "answered", "answer": answer, "citation_indices": indices}, evidence, "Question")
    assert response.status == "insufficient_evidence"
    assert response.citations == []


def test_citations_follow_first_reference_and_reuse_verified_metadata():
    from app.ai.service import validate_answer

    evidence = [
        Evidence(uuid4(), uuid4(), slug, title, url, excerpt, locator)
        for slug, title, url, excerpt, locator in [
            ("flex", "FLEX", "https://example.org/flex", "First excerpt", "Methods"),
            ("bass", "BASS", "https://example.org/bass", "Second excerpt", "Results"),
        ]
    ]
    response = validate_answer(
        {"status": "answered", "answer": "One [2]. Two [1]. Again [2].", "citation_indices": [2, 1]},
        evidence, "Question",
    )
    assert response.answer == "One [1]. Two [2]. Again [1]."
    assert response.related_study_ids == ["bass", "flex"]
    for citation, item in zip(response.citations, reversed(evidence), strict=True):
        assert (citation.chunk_id, citation.source_id, citation.url, citation.excerpt, citation.locator) == (
            item.chunk_id, item.source_id, item.url, item.excerpt, item.locator,
        )


def test_reranker_receives_experiment_title_and_section():
    import json

    import httpx

    from app.ai.providers import JsonAPI
    from app.ai.reranking import RemoteReranker

    def respond(request):
        document, = json.loads(request.content)["documents"]
        assert "FLEX-1" in document and "Methods" in document and "Excerpt" in document
        return httpx.Response(200, json={"results": [{"index": 0}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            reranker = RemoteReranker(JsonAPI(client, "https://example.test", "mock-key", 1, 0), "mock")
            evidence = Evidence(uuid4(), uuid4(), "flex-1", "FLEX-1", "https://example.org", "Excerpt", "Methods")
            assert await reranker.rerank("How was FLEX-1 conducted?", [evidence]) == [0]

    asyncio.run(run())


def test_openrouter_uses_configured_budget_and_reports_truncation():
    import json

    import httpx

    from app.ai.llm import RemoteLLM
    from app.ai.providers import JsonAPI

    def respond(request):
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 3200
        assert payload["reasoning"] == {"enabled": False}
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"finish_reason": "length"}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            llm = RemoteLLM(JsonAPI(client, "https://openrouter.ai/api/v1", "mock-key", 1, 0), "mock", 3200)
            with pytest.raises(ProviderUnavailable, match="token limit"):
                await llm.generate([{"role": "user", "content": "Test"}])

    asyncio.run(run())


def test_insufficient_evidence_never_returns_related_claims_or_citations():
    from app.ai.service import validate_answer

    item = Evidence(uuid4(), uuid4(), "flex", "Report", "https://example.org", "The instrument was used", None)
    result = validate_answer({
        "status": "insufficient_evidence",
        "answer": "The instrument was used [1].",
        "citation_indices": [1],
    }, [item], "What was the instrument's serial number?")
    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert not result.related_study_ids


def test_dialogue_suggestions_are_optional_and_safe_to_display():
    from app.ai.service import validate_answer

    item = Evidence(uuid4(), uuid4(), "flex", "Report", "https://example.org", "Contrast observation", None)
    result = validate_answer({
        "status": "answered",
        "answer": "Contrast made the sample easier to see [1].",
        "citation_indices": [1],
        "suggested_questions": [
            "  How did the researchers compare the samples? ",
            "how did the researchers compare the samples?",
            {"unexpected": True},
            "Where is [1](https://example.org)?",
            "Would you like to know more",
            "What conditions did they test?",
            "What did the report say about limitations?",
        ],
    }, [item], "What was observed?")
    assert result.status == "answered"
    assert result.suggested_questions == [
        "How did the researchers compare the samples?",
        "What conditions did they test?",
    ]


def test_missing_fact_can_offer_targeted_questions_without_claims():
    from app.ai.service import validate_answer

    item = Evidence(uuid4(), uuid4(), "flex", "Report", "https://example.org", "A setup used two samples", None)
    result = validate_answer({
        "status": "insufficient_evidence",
        "answer": "An unsupported guess.",
        "citation_indices": [1],
        "suggested_questions": ["How was the experiment set up?"],
    }, [item], "What was the instrument's serial number?")
    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert "unsupported guess" not in result.answer
    assert result.suggested_questions == ["How was the experiment set up?"]

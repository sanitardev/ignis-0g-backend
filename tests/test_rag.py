import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

from app.ai import service
from app.ai.ingestion import split_text
from app.ai.retrieval import Evidence
from app.schemas.assistant import ChatRequest


def test_chunking_preserves_text_and_bounds():
    text = " ".join(f"word-{number}" for number in range(200))
    chunks = list(split_text(text, size=100, overlap=20))
    assert chunks[0].startswith("word-0 ")
    assert chunks[-1].endswith("word-199")
    assert all(0 < len(chunk) <= 100 and chunk in text for chunk in chunks)


def test_answer_uses_database_citations_and_study_scope(monkeypatch):
    evidence = Evidence(uuid4(), uuid4(), "flex", "Report", "https://example.org", "Excerpt", "p. 3")
    retrieve = AsyncMock(return_value=[evidence])
    generate = AsyncMock(return_value={"answer": "Supported [1].", "citation_indices": [1]})
    monkeypatch.setattr(service, "retrieve", retrieve)
    monkeypatch.setattr(service, "generate", generate)

    request = ChatRequest(message="What was reported?", study_id="flex")
    result = asyncio.run(service.ask(request))
    retrieve.assert_awaited_once_with(request)
    assert result.status == "answered"
    assert result.related_study_ids == ["flex"]
    assert result.citations[0].chunk_id == evidence.chunk_id
    assert result.citations[0].excerpt == "Excerpt"

    generate.return_value = {"answer": "Invented [2].", "citation_indices": [2]}
    assert asyncio.run(service.ask(request)).status == "insufficient_evidence"

    generate.return_value = {"answer": "Supported.", "citation_indices": [1]}
    assert asyncio.run(service.ask(request)).answer == "Supported. [1]"

    generate.reset_mock()
    retrieve.return_value = []
    assert asyncio.run(service.ask(request)).status == "insufficient_evidence"
    generate.assert_not_called()


def test_indexing_scope_stale_sources_and_citations(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.ai import ingestion, retrieval
    from app.core.database import engine
    from app.schemas.ingestion import Package
    from app.services.ingestion import import_package

    vector = "[" + ",".join(["1", *["0"] * 383]) + "]"
    monkeypatch.setattr(ingestion, "embed", lambda texts: [vector] * len(texts))
    monkeypatch.setattr(retrieval, "embed", lambda texts: [vector] * len(texts))
    monkeypatch.setattr(service, "generate", AsyncMock(
        return_value={"answer": "Supported [1].", "citation_indices": [1]}
    ))

    async def run():
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            monkeypatch.setattr(ingestion, "session_factory", factory)
            monkeypatch.setattr(retrieval, "session_factory", factory)
            raw = {"schema_version": 1, "studies": [
                {
                    "slug": f"rag-{suffix}", "title": "Synthetic",
                    "description": "Test data", "category": "test",
                    "sources": [{
                        "source_key": "example", "title": f"Report {suffix}",
                        "url": "https://example.org/report", "source_type": "report",
                        "text_content": f"Synthetic excerpt {suffix}",
                    }],
                }
                for suffix in ("one", "two")
            ]}
            try:
                await import_package(Package.model_validate(raw), factory=factory)
                assert await ingestion.index_sources() == 2
                assert await ingestion.index_sources() == 0
                query = ChatRequest(message="What was reported?", study_id="rag-one")
                answer = await service.ask(query)
                assert answer.status == "answered"
                assert answer.related_study_ids == ["rag-one"]
                assert answer.citations[0].excerpt == "Synthetic excerpt one"
                old_chunk = answer.citations[0].chunk_id

                raw["studies"][0]["sources"][0]["text_content"] = "Revised passage"
                await import_package(Package.model_validate(raw), factory=factory)
                assert (await service.ask(query)).status == "insufficient_evidence"
                assert await ingestion.index_sources() == 1
                answer = await service.ask(query)
                assert answer.citations[0].excerpt == "Revised passage"
                assert answer.citations[0].chunk_id != old_chunk

                raw["studies"][0]["sources"][0]["text_content"] = None
                await import_package(Package.model_validate(raw), factory=factory)
                assert await ingestion.index_sources() == 1
                assert (await service.ask(query)).status == "insufficient_evidence"
            finally:
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(run())

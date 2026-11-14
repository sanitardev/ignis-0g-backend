import logging
import re
from time import monotonic

logger = logging.getLogger("uvicorn.error.rag")

from pydantic import BaseModel, ConfigDict, ValidationError

from app.ai.embeddings import vector_parameter
from app.ai.ingestion import index_revision
from app.ai.prompts import build_messages, rewrite_messages
from app.ai.providers import EmbeddingProvider, LLMProvider, ProviderUnavailable, RerankerProvider
from app.ai.retrieval import Evidence, PgVectorRepository
from app.ai.settings import RagSettings, settings_from_env
from app.ai.wiring import configured_providers
from app.schemas.assistant import ChatRequest, ChatResponse, Citation


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(strict=True)
    answer: str
    citation_indices: list[int]


def insufficient_evidence(question: str = "") -> ChatResponse:
    russian = not question or bool(re.search(r"[А-Яа-яЁё]", question))
    message = (
        "В доступных источниках недостаточно данных для подтвержденного ответа."
        if russian else "The available sources do not provide enough evidence to answer."
    )
    return ChatResponse(
        status="insufficient_evidence",
        answer=message,
        citations=[],
        related_study_ids=[],
        suggested_questions=[],
    )


class RagService:
    def __init__(
        self, embedding: EmbeddingProvider, reranker: RerankerProvider | None,
        llm: LLMProvider, settings: RagSettings, repository: PgVectorRepository,
    ):
        self.embedding = embedding
        self.reranker = reranker
        self.llm = llm
        self.settings = settings
        self.repository = repository

    async def ask(self, request: ChatRequest) -> ChatResponse:
        started = monotonic()
        revision = index_revision(self.embedding, self.settings)
        if not await self.repository.has_chunks(request, revision):
            logger.info("rag outcome=no_index")
            return insufficient_evidence(request.message)

        query = request.message
        if request.history:
            try:
                rewritten = await self.llm.generate(rewrite_messages(request))
            except ProviderUnavailable:
                logger.info("rag stage=rewrite outcome=fallback")
                rewritten = None
            if isinstance(rewritten, dict) and isinstance(rewritten.get("query"), str):
                candidate = rewritten["query"].strip()
                if 0 < len(candidate) <= 2000:
                    query = candidate

        logger.info("rag stage=embedding")
        vector = vector_parameter(await self.embedding.embed_query(query))
        evidence = await self.repository.search(request, vector, revision, self.settings.candidate_limit)
        logger.info("rag stage=retrieval candidates=%d", len(evidence))
        if not evidence:
            return insufficient_evidence(request.message)
        if self.reranker:
            try:
                ranking = await self.reranker.rerank(query, evidence)
                if all(type(index) is int and 0 <= index < len(evidence) for index in ranking):
                    ranking = list(dict.fromkeys(ranking))
                    ranked = set(ranking)
                    evidence = [evidence[index] for index in ranking] + [
                        item for index, item in enumerate(evidence) if index not in ranked
                    ]
            except ProviderUnavailable:
                logger.info("rag stage=rerank outcome=fallback")

        context = evidence[:self.settings.context_limit]
        logger.info("rag stage=generation context_count=%d", len(context))
        result = validate_answer(await self.llm.generate(build_messages(request, context)), context, request.message)
        logger.info("rag outcome=%s citations=%d elapsed_ms=%d", result.status, len(result.citations), (monotonic() - started) * 1000)
        return result


async def ask(request: ChatRequest) -> ChatResponse:
    settings = settings_from_env()
    async with configured_providers(settings) as (embedding, reranker, llm):
        return await RagService(embedding, reranker, llm, settings, PgVectorRepository()).ask(request)


def validate_answer(raw: object, evidence: list[Evidence], question: str) -> ChatResponse:
    try:
        result = GroundedAnswer.model_validate(raw)
    except ValidationError:
        logger.info("rag stage=validation outcome=invalid_response_shape")
        return insufficient_evidence(question)

    answer = result.answer.strip()
    markers = list(dict.fromkeys(re.findall(r"\[([0-9]+)\]", answer)))
    indices = result.citation_indices
    reason = None
    if not answer:
        reason = 'empty_answer'
    elif re.search(r"<(?:/?[A-Za-z]|!--)", answer):
        reason = 'html_in_answer'
    elif not indices:
        reason = 'no_citations'
    elif len(set(indices)) != len(indices) or any(not 1 <= index <= len(evidence) for index in indices):
        reason = 'invalid_citation_indices'
    elif markers != [str(index) for index in indices]:
        reason = 'citation_marker_mismatch'
    if reason:
        logger.info("rag stage=validation outcome=%s", reason)
        return insufficient_evidence(question)

    cited = [evidence[index - 1] for index in indices]
    renumber = {str(index): str(number) for number, index in enumerate(indices, start=1)}
    answer = re.sub(r"\[([0-9]+)\]", lambda match: f"[{renumber[match[1]]}]", answer)
    citations = [
        Citation(
            chunk_id=item.chunk_id, source_id=item.source_id, title=item.title,
            url=item.url, excerpt=item.excerpt, locator=item.locator,
        )
        for item in cited
    ]
    return ChatResponse(
        status="answered",
        answer=answer,
        citations=citations,
        related_study_ids=list(dict.fromkeys(item.study_slug for item in cited)),
        suggested_questions=[],
    )

import logging
import re
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.ai.embeddings import vector_parameter
from app.ai.ingestion import index_revision
from app.ai.prompts import build_messages, rewrite_messages
from app.ai.providers import EmbeddingProvider, LLMProvider, ProviderUnavailable, RerankerProvider
from app.ai.retrieval import Evidence, PgVectorRepository
from app.ai.settings import RagSettings, settings_from_env
from app.ai.wiring import configured_providers
from app.schemas.assistant import ChatRequest, ChatResponse, Citation


logger = logging.getLogger("uvicorn.error.rag")


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(strict=True)
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    suggested_questions: object = None


def insufficient_evidence(
    question: str = "", *, suggestions: list[str] | None = None,
) -> ChatResponse:
    russian = not question or bool(re.search(r"[А-Яа-яЁё]", question))
    message = (
        "В доступных источниках пока нет сведений, на которые можно опереться для ответа."
        if russian else "I couldn’t find enough evidence in the available sources to answer this question."
    )
    return ChatResponse(
        status="insufficient_evidence",
        answer=message,
        citations=[],
        related_study_ids=[],
        suggested_questions=suggestions or [],
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

        context = select_context(evidence, self.settings.context_limit, diversify=request.scope == "global")
        logger.info("rag stage=generation context_count=%d", len(context))
        result = validate_answer(await self.llm.generate(build_messages(request, context)), context, request.message)
        logger.info("rag outcome=%s citations=%d elapsed_ms=%d", result.status, len(result.citations), (monotonic() - started) * 1000)
        return result


async def ask(request: ChatRequest) -> ChatResponse:
    settings = settings_from_env()
    async with configured_providers(settings) as (embedding, reranker, llm):
        return await RagService(embedding, reranker, llm, settings, PgVectorRepository()).ask(request)


def select_context(evidence: list[Evidence], limit: int, *, diversify: bool = False) -> list[Evidence]:
    selected = []
    deferred = []
    seen_passages = set()
    seen_studies = set()
    for item in evidence:
        key = (item.study_slug, " ".join(item.excerpt.casefold().split()))
        if key in seen_passages:
            continue
        seen_passages.add(key)
        if diversify and item.study_slug in seen_studies:
            deferred.append(item)
        else:
            selected.append(item)
            seen_studies.add(item.study_slug)
        if len(selected) == limit:
            break
    return (selected + deferred)[:limit]


def suggested_questions(raw: object, current_question: str) -> list[str]:
    if not isinstance(raw, list):
        return []
    questions = []
    seen = {" ".join(current_question.casefold().split())}
    for item in raw:
        if not isinstance(item, str):
            continue
        question = " ".join(item.split())
        if (
            not 5 <= len(question) <= 160
            or not question.endswith(("?", "？", "؟"))
            or re.search(r"[<>\[\]`]|://", question)
        ):
            continue
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        questions.append(question)
        if len(questions) == 2:
            break
    return questions


def validate_answer(raw: object, evidence: list[Evidence], question: str) -> ChatResponse:
    try:
        result = GroundedAnswer.model_validate(raw)
    except ValidationError:
        logger.info("rag stage=validation outcome=invalid_response_shape")
        return insufficient_evidence(question)

    suggestions = suggested_questions(result.suggested_questions, question)
    if result.status == "insufficient_evidence":
        return insufficient_evidence(question, suggestions=suggestions)

    answer = result.answer.strip()
    markers = list(dict.fromkeys(re.findall(r"\[([0-9]+)\]", answer)))
    valid_markers = {str(index) for index in range(1, len(evidence) + 1)}
    reason = None
    if not answer:
        reason = 'empty_answer'
    elif re.search(r"<(?:/?[A-Za-z]|!--)", answer):
        reason = 'html_in_answer'
    elif not markers:
        reason = 'no_citations'
    elif any(marker not in valid_markers for marker in markers):
        reason = 'invalid_citation_indices'
    elif re.search(r"\[[0-9]+\]\s*\([^\n)]*\)|(?m:^\s{0,3}\[[0-9]+\]:)", answer):
        reason = 'linked_citation'
    if reason:
        logger.info("rag stage=validation outcome=%s", reason)
        return insufficient_evidence(question)

    cited = [evidence[int(marker) - 1] for marker in markers]
    renumber = {marker: str(number) for number, marker in enumerate(markers, start=1)}
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
        suggested_questions=suggestions,
    )

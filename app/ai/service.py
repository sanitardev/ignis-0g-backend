import re

from pydantic import BaseModel, ConfigDict, ValidationError

from app.ai.llm import generate
from app.ai.prompts import build_messages
from app.ai.retrieval import retrieve
from app.schemas.assistant import ChatRequest, ChatResponse, Citation


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(strict=True)
    answer: str
    citation_indices: list[int]


def insufficient_evidence() -> ChatResponse:
    return ChatResponse(
        status="insufficient_evidence",
        answer="В доступных источниках недостаточно данных для подтвержденного ответа.",
        citations=[],
        related_study_ids=[],
        suggested_questions=[],
    )


async def ask(request: ChatRequest) -> ChatResponse:
    evidence = await retrieve(request)
    if not evidence:
        return insufficient_evidence()

    raw = await generate(build_messages(request, evidence))
    try:
        result = GroundedAnswer.model_validate(raw)
    except ValidationError:
        return insufficient_evidence()

    answer = result.answer.strip()
    markers = list(dict.fromkeys(re.findall(r"\[([0-9]+)\]", answer)))
    indices = result.citation_indices
    if (
        not answer
        or not indices
        or any(not 1 <= index <= len(evidence) for index in indices)
        or (markers and markers != [str(index) for index in indices])
    ):
        return insufficient_evidence()

    cited = [evidence[index - 1] for index in indices]
    renumber = {str(index): str(number) for number, index in enumerate(indices, start=1)}
    if markers:
        answer = re.sub(r"\[([0-9]+)\]", lambda match: f"[{renumber[match[1]]}]", answer)
    else:
        answer += " " + " ".join(f"[{number}]" for number in renumber.values())
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

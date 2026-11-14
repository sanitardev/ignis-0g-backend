from app.schemas.assistant import ChatRequest, ChatResponse

async def ask(request: ChatRequest) -> ChatResponse:
    return ChatResponse(status='insufficient_evidence', answer='В доступных источниках недостаточно данных для подтвержденного ответа.', citations=[], related_study_ids=[], suggested_questions=[])

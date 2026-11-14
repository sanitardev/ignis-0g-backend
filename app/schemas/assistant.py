from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator

class ChatMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=2000)

    @field_validator('content', mode='before')
    @classmethod
    def strip_content(cls, value):
        return value.strip() if isinstance(value, str) else value

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    study_id: str | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    scope: Literal['study', 'global'] | None = None

    @field_validator('message', mode='before')
    @classmethod
    def strip_message(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode='after')
    def normalize(self):
        if sum(len(item.content) for item in self.history) > 12000:
            raise ValueError('history exceeds 12000 characters')
        if self.scope is None:
            self.scope = 'study' if self.study_id else 'global'
        if self.scope == 'study' and not self.study_id:
            raise ValueError('study scope requires study_id')
        return self

class Citation(BaseModel):
    chunk_id: UUID
    source_id: UUID
    title: str
    url: str
    excerpt: str
    locator: str | None

class ChatResponse(BaseModel):
    status: Literal['answered', 'insufficient_evidence']
    answer: str
    citations: list[Citation]
    related_study_ids: list[str]
    suggested_questions: list[str]

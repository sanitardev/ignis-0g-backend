from os import getenv

from pydantic import BaseModel, Field, model_validator


class RagSettings(BaseModel):
    chunk_tokens: int = Field(400, ge=32, le=2048)
    chunk_overlap: int = Field(50, ge=0)
    candidate_limit: int = Field(20, ge=1, le=100)
    context_limit: int = Field(5, ge=1, le=20)
    batch_size: int = Field(32, ge=1, le=128)
    timeout: float = Field(4, gt=0, le=30)
    retries: int = Field(1, ge=0, le=2)

    @model_validator(mode="after")
    def validate_limits(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        if self.context_limit > self.candidate_limit:
            raise ValueError("context_limit must not exceed candidate_limit")
        return self


def settings_from_env() -> RagSettings:
    return RagSettings.model_validate({
        field: getenv(f"RAG_{field.upper()}", str(config.default))
        for field, config in RagSettings.model_fields.items()
    })

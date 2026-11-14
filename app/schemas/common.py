from typing import Literal
from pydantic import BaseModel

class ErrorDetail(BaseModel):
    field: str
    message: str

class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[ErrorDetail]

class ErrorResponse(BaseModel):
    error: ErrorBody

class Health(BaseModel):
    status: Literal['ok']
    database: Literal['ok']

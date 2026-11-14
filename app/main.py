from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.ai.service import ask
from app.schemas.assistant import ChatRequest, ChatResponse
from app.schemas.study import StudyDetail, StudyList, CatalogFilters, Dataset

from app.core.database import lifespan, session_factory
from app.repositories import catalog as repository
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

app = FastAPI(title='IGNIS 0G API', version='0.1.0', lifespan=lifespan)

def error(request: Request, status: int, code: str, message: str, details=None):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message, 'request_id': request.state.request_id, 'details': details or []}})

@app.middleware('http')
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    try:
        response = await call_next(request)
    except (SQLAlchemyError, OSError, TimeoutError):
        response = error(request, 503, 'DATABASE_UNAVAILABLE', 'Database unavailable')
    response.headers['X-Request-ID'] = request.state.request_id
    return response

@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    code, message = exc.detail if isinstance(exc.detail, tuple) else ('NOT_FOUND' if exc.status_code == 404 else 'HTTP_ERROR', str(exc.detail))
    return error(request, exc.status_code, code, message)

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return error(request, 422, 'VALIDATION_ERROR', 'Invalid request', [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()])

@app.get('/api/v1/studies', response_model=StudyList)
async def studies(q: str | None = Query(None, max_length=200), category: str | None = Query(None, max_length=80), tag: str | None = Query(None, max_length=80), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return await repository.catalog(q, category, tag, limit, offset)

@app.get('/api/v1/catalog/filters', response_model=CatalogFilters)
async def filters():
    return await repository.filters()

@app.get('/api/v1/studies/{study_id}', response_model=StudyDetail)
async def study_detail(study_id: str):
    return await repository.detail(study_id)

@app.get('/api/v1/studies/{study_id}/datasets', response_model=list[Dataset])
async def datasets(study_id: str):
    return await repository.datasets(study_id)

@app.get('/api/v1/studies/{study_id}/datasets/{dataset_id}', response_model=Dataset)
async def dataset(study_id: str, dataset_id: UUID):
    return await repository.datasets(study_id, dataset_id)

@app.post('/api/v1/assistant/chat', response_model=ChatResponse)
async def chat(request: ChatRequest):
    if request.study_id is not None:
        await repository.require_study(request.study_id)
    return await ask(request)

@app.get('/health')
async def health(request: Request):
    async with session_factory() as session:
        await session.execute(text('SELECT 1'))
    return {'status': 'ok', 'database': 'ok'}

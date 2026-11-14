import logging
import os
import time
import asyncio
from uuid import UUID, uuid4
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.schemas.common import ErrorResponse, Health
from app.schemas.study import Finding, Source, Media
from app.schemas.assistant import CompareRequest, CompareResponse
from app.schemas.nexus import Relation, Graph
from app.repositories import nexus
from app.ai.providers import ProviderTimeout, ProviderUnavailable
from app.ai.service import ask
from app.schemas.assistant import ChatRequest, ChatResponse
from app.schemas.study import StudyDetail, StudyList, CatalogFilters, Dataset

from app.core.database import lifespan, session_factory
from app.repositories import catalog as repository
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

app = FastAPI(title='IGNIS 0G API', version='0.1.0', lifespan=lifespan, responses={code: {'model': ErrorResponse} for code in [404,405,413,422,429,500,503,504]})
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','), allow_methods=['GET','POST'], allow_headers=['Content-Type'], expose_headers=['X-Request-ID','Retry-After'])
rate_windows = {}

def error(request: Request, status: int, code: str, message: str, details=None):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message, 'request_id': request.state.request_id, 'details': details or []}})

@app.middleware('http')
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    try:
        if request.url.path.startswith('/api/v1/assistant/') and request.method == 'POST':
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 32768:
                    raise HTTPException(413, ('PAYLOAD_TOO_LARGE', 'Body exceeds 32 KiB'))
                chunks.append(chunk)
            request._body = b''.join(chunks)
            now = time.monotonic()
            for key in list(rate_windows):
                if now - rate_windows[key][0] >= 60:
                    del rate_windows[key]
            client = request.client.host if request.client else 'unknown'
            start, count = rate_windows.get(client, (now, 0))
            if count >= 5:
                raise HTTPException(429, ('RATE_LIMITED','Request limit exceeded'), headers={'Retry-After':str(max(1,int(60-(now-start))))})
            rate_windows[client] = (start,count+1)
        timeout = 40 if request.url.path == '/api/v1/assistant/chat' else 10
        async with asyncio.timeout(timeout):
            response = await call_next(request)
    except HTTPException as exc:
        response = await http_error(request, exc)
    except (SQLAlchemyError, OSError, TimeoutError):
        response = error(request, 503, 'DATABASE_UNAVAILABLE', 'Database unavailable')
    except Exception:
        logging.getLogger(__name__).error('Unhandled request error request_id=%s', request.state.request_id)
        response = error(request,500,'INTERNAL_ERROR','Internal server error')
    response.headers['X-Request-ID'] = request.state.request_id
    if request.headers.get('origin') in os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','):
        response.headers['Access-Control-Allow-Origin'] = request.headers['origin']
        response.headers['Access-Control-Expose-Headers'] = 'X-Request-ID, Retry-After'
        response.headers.add_vary_header('Origin')
    return response

@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: HTTPException):
    code, message = exc.detail if isinstance(exc.detail, tuple) else ('NOT_FOUND' if exc.status_code == 404 else 'HTTP_ERROR', str(exc.detail))
    response = error(request, exc.status_code, code, message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response

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
    try:
        async with asyncio.timeout(35):
            return await ask(request)
    except (ProviderTimeout, TimeoutError):
        raise HTTPException(504, ('AI_TIMEOUT', 'Assistant request timed out')) from None
    except ProviderUnavailable:
        raise HTTPException(503, ('AI_UNAVAILABLE', 'Assistant unavailable')) from None

@app.get('/health', response_model=Health)
async def health(request: Request):
    async with session_factory() as session:
        await session.execute(text('SELECT 1'))
    return {'status': 'ok', 'database': 'ok'}

@app.get('/api/v1/studies/{study_id}/findings', response_model=list[Finding])
async def findings(study_id: str):
    return (await repository.detail(study_id)).findings

@app.get('/api/v1/studies/{study_id}/sources', response_model=list[Source])
async def sources(study_id: str):
    return (await repository.detail(study_id)).sources

@app.get('/api/v1/studies/{study_id}/media', response_model=list[Media])
async def media(study_id: str):
    return (await repository.detail(study_id)).media

@app.get('/api/v1/studies/{study_id}/relations', response_model=list[Relation])
async def relations(study_id: str):
    return await nexus.relations(study_id)

@app.get('/api/v1/nexus/graph', response_model=Graph)
async def graph(study_id: str | None = None, depth: int = Query(1, ge=1, le=2)):
    return await nexus.graph(study_id, depth)

@app.post('/api/v1/assistant/compare', response_model=CompareResponse)
async def compare(request: CompareRequest):
    for study_id in request.study_ids:
        await repository.require_study(study_id)
    return CompareResponse(status='insufficient_evidence',summary='AI comparison is not enabled.',similarities=[],differences=[],limitations=['AI integration is pending.'],citations=[])


@app.get("/chat", include_in_schema=False)
async def chat_page():
    return FileResponse(Path(__file__).with_name("static") / "chat.html", media_type="text/html")

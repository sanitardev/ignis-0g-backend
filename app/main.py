from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.ai.service import ask
from app.schemas.assistant import ChatRequest, ChatResponse
from app.schemas.study import StudyDetail, StudyList, CatalogFilters, Dataset

app = FastAPI(title='IGNIS 0G Mock API', version='0.1.0')

# Deliberately fictional: no scientific findings or numeric measurements.
STUDIES = [StudyDetail(id='demo-study', title='Demo study (fictional)', description='Synthetic fixture for API integration; not scientific data.', category='demo', tags=['mock'], thumbnail_url=None, methodology=None, conditions={}, findings=[], sources=[], media=[], datasets=[], safety_implications=[])]
DATASETS: dict[str, list[Dataset]] = {'demo-study': []}

def error(request: Request, status: int, code: str, message: str, details=None):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message, 'request_id': request.state.request_id, 'details': details or []}})

@app.middleware('http')
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers['X-Request-ID'] = request.state.request_id
    return response

@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    code, message = exc.detail if isinstance(exc.detail, tuple) else ('NOT_FOUND' if exc.status_code == 404 else 'HTTP_ERROR', str(exc.detail))
    return error(request, exc.status_code, code, message)

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return error(request, 422, 'VALIDATION_ERROR', 'Invalid request', [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()])

def get_study(study_id: str) -> StudyDetail:
    study = next((s for s in STUDIES if s.id == study_id), None)
    if study is None:
        raise HTTPException(404, detail=('STUDY_NOT_FOUND', 'Study not found'))
    return study

@app.get('/api/v1/studies', response_model=StudyList)
async def studies(q: str | None = Query(None, max_length=200), category: str | None = Query(None, max_length=80), tag: str | None = Query(None, max_length=80), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    query = (q or '').strip().casefold()
    def rank(s):
        if not query: return 0
        fields = [s.title, ' '.join(s.tags), s.description, ' '.join(f.claim for f in s.findings)]
        return next((i for i, field in enumerate(fields) if query in field.casefold()), 4)
    items = [s for s in STUDIES if (category is None or s.category == category) and (tag is None or tag in s.tags) and rank(s) < 4]
    items.sort(key=lambda s: (rank(s), s.title, s.id))
    return StudyList(items=items[offset:offset + limit], total=len(items), limit=limit, offset=offset)

@app.get('/api/v1/catalog/filters', response_model=CatalogFilters)
async def filters():
    return CatalogFilters(categories=sorted({s.category for s in STUDIES}), tags=sorted({t for s in STUDIES for t in s.tags}))

@app.get('/api/v1/studies/{study_id}', response_model=StudyDetail)
async def study_detail(study_id: str):
    return get_study(study_id)

@app.get('/api/v1/studies/{study_id}/datasets', response_model=list[Dataset])
async def datasets(study_id: str):
    get_study(study_id)
    return DATASETS.get(study_id, [])

@app.get('/api/v1/studies/{study_id}/datasets/{dataset_id}', response_model=Dataset)
async def dataset(study_id: str, dataset_id: UUID):
    get_study(study_id)
    result = next ( (d for d in DATASETS.get(study_id, []) if d.id == dataset_id), None)
    if result is None:
        raise HTTPException(404, detail=('DATASET_NOT_FOUND', 'Dataset not found'))
    return result

@app.post('/api/v1/assistant/chat', response_model=ChatResponse)
async def chat(request: ChatRequest):
    if request.study_id is not None:
        get_study(request.study_id)
    return await ask(request)

@app.get('/health')
async def health(request: Request):
    return error(request, 503, 'DATABASE_UNAVAILABLE', 'Mock server has no database connection')

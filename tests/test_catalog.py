"""Integration test: requires migrated local PostgreSQL; inserts are rolled back."""
import asyncio
from uuid import uuid4
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.main import app
from app.core.database import engine
from app.repositories import catalog
from app.models import Study, Source, Finding, Dataset


def test_database_api():
    async def run():
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(connection, expire_on_commit=False)
            original = catalog.session_factory
            catalog.session_factory = factory
            try:
                key = 'test-' + uuid4().hex
                async with factory() as session:
                    a = Study(slug=key, title='A flame', description='literal %', category=key, tags=['tag'])
                    b = Study(slug=key+'-b', title='B study', description='flame', category=key, tags=[])
                    session.add_all([a,b]); await session.flush()
                    source = Source(study_id=a.id, source_key='s', title='Synthetic', url='https://example.com', source_type='other')
                    session.add(source); await session.flush()
                    session.add(Finding(study_id=a.id, source_id=source.id, finding_key='f', claim='uniqueclaim', evidence='synthetic', safety_impact='test only'))
                    data = Dataset(study_id=a.id, source_id=source.id, dataset_key='d', title='Synthetic', chart_type='line', units={'x':'s','y':'K'}, data={'x_label':'time','y_label':'value','series':[{'id':'s','label':'Synthetic','points':[{'x':0,'y':None}]}],'provenance':'reported'})
                    session.add(data); await session.flush()
                    dataset_id = str(data.id)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                    r = await client.get('/health'); assert r.json() == {'status':'ok','database':'ok'}
                    r = await client.get('/api/v1/studies', params={'category':key,'q':'flame','limit':1}); assert r.json()['total']==2 and r.json()['items'][0]['id']==key
                    r = await client.get('/api/v1/studies', params={'category':key,'offset':10}); assert r.json()['items']==[] and r.json()['total']==2
                    for q in ['%', 'uniqueclaim']:
                        r = await client.get('/api/v1/studies', params={'category':key,'q':q}); assert r.json()['total']==1
                    r = await client.get('/api/v1/studies', params={'category':key,'tag':'missing'}); assert r.json()['total']==0
                    r = await client.get('/api/v1/studies/'+key); assert len(r.json()['safety_implications'])==1 and r.json()['sources'][0]['study_id']==key
                    r = await client.get(f'/api/v1/studies/{key}/datasets/{dataset_id}'); assert r.json()['series'][0]['points'][0]['y'] is None
                    r = await client.get(f'/api/v1/studies/{key}-b/datasets/{dataset_id}'); assert r.status_code==404
                    r = await client.get('/api/v1/studies/'+key+'/datasets/invalid'); assert r.status_code==422
                    r = await client.get('/api/v1/catalog/filters'); assert key in r.json()['categories']
                    r = await client.post('/api/v1/assistant/chat', json={'message':'hello','study_id':key}); assert r.json()['status']=='insufficient_evidence'
                    r = await client.get('/api/v1/studies/missing-'+key); assert r.status_code==404 and r.json()['error']['request_id']==r.headers['x-request-id']
            finally:
                catalog.session_factory = original
                await transaction.rollback()
        await engine.dispose()
    asyncio.run(run())


def test_unavailable_database(monkeypatch):
    from contextlib import asynccontextmanager
    import importlib
    main = importlib.import_module('app.main')

    @asynccontextmanager
    async def unavailable():
        raise OSError('connection refused')
        yield

    monkeypatch.setattr(main, 'session_factory', unavailable)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/health')
            assert response.status_code == 503
            assert response.json()['error']['code'] == 'DATABASE_UNAVAILABLE'
            assert response.json()['error']['request_id'] == response.headers['x-request-id']
    asyncio.run(run())

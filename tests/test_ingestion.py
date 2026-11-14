import asyncio
from uuid import uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.database import engine
from app.models import Study, Source, Finding
from app.schemas.ingestion import Package, Dataset
from app.services.ingestion import import_package


def test_import():
    async def run():
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(connection,expire_on_commit=False,join_transaction_mode='create_savepoint')
            try:
                slug='import-'+uuid4().hex
                raw={'schema_version':1,'studies':[{'slug':slug,'title':'Synthetic','description':'test only','category':'test','sources':[{'source_key':'s','title':'Synthetic','url':'https://example.com','source_type':'other','text_content':'old'}],'findings':[{'finding_key':'f','source_key':'s','claim':'synthetic','evidence':'test'}]}]}
                package=Package.model_validate(raw)
                await import_package(package,dry_run=True,factory=factory)
                async with factory() as session:
                    assert await session.scalar(select(Study.id).where(Study.slug==slug)) is None
                await import_package(package,factory=factory)
                async with factory() as session:
                    id_=await session.scalar(select(Study.id).where(Study.slug==slug))
                    source=await session.scalar(select(Source).where(Source.study_id==id_))
                    source_id,old_hash=source.id,source.content_hash
                    finding_id=await session.scalar(select(Finding.id).where(Finding.study_id==id_))
                await import_package(package,factory=factory)
                raw['studies'][0]['sources'][0]['text_content']='new'
                raw['studies'][0]['findings']=[]
                await import_package(Package.model_validate(raw),factory=factory)
                async with factory() as session:
                    source=await session.get(Source,source_id)
                    assert source.content_hash != old_hash
                    assert await session.get(Finding,finding_id) is not None
                    assert list(await session.scalars(select(Source.id).where(Source.study_id==id_))) == [source_id]
                raw['studies'][0]['title']='must not be written'
                raw['studies'][0]['findings']=[{'finding_key':'bad','source_key':'absent','claim':'x','evidence':'x'}]
                with pytest.raises(ValueError,match='unknown source_key'):
                    await import_package(Package.model_validate(raw),factory=factory)
                async with factory() as session:
                    assert (await session.get(Study,id_)).title=='Synthetic'
            finally:
                await transaction.rollback()
        await engine.dispose()
    asyncio.run(run())

@pytest.mark.parametrize('change',[
    {'series':[{'id':'s','label':'s','points':[{'x':2,'y':1},{'x':1,'y':2}]}]},
    {'series':[{'id':'s','label':'s','points':[{'x':1,'y':float('nan')}]}]},
    {'provenance':'derived'},
])
def test_invalid_dataset(change):
    raw=dict(dataset_key='d',source_key='s',title='Synthetic',chart_type='line',x_label='x',y_label='y',units={'x':'s','y':'K'},series=[],provenance='reported')
    raw.update(change)
    with pytest.raises(ValueError):
        Dataset.model_validate(raw)


def test_database_failure_rolls_back(monkeypatch):
    from app.services import ingestion
    async def run():
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(connection,expire_on_commit=False,join_transaction_mode='create_savepoint')
            slug='rollback-'+uuid4().hex
            original=ingestion.upsert
            calls=0
            async def failing(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==2:
                    raise RuntimeError('simulated write failure')
                return await original(*args,**kwargs)
            monkeypatch.setattr(ingestion,'upsert',failing)
            package=Package.model_validate({'schema_version':1,'studies':[{'slug':slug,'title':'test','description':'test','category':'test','sources':[{'source_key':'s','title':'test','url':'https://example.com','source_type':'other'}]}]})
            try:
                with pytest.raises(RuntimeError):
                    await import_package(package,factory=factory)
                async with factory() as session:
                    assert await session.scalar(select(Study.id).where(Study.slug==slug)) is None
            finally:
                await transaction.rollback()
        await engine.dispose()
    asyncio.run(run())

@pytest.mark.parametrize('change',[
    {'schema_version':2},
    {'studies':[{'slug':'BAD SLUG','title':'a','description':'a','category':'a'}]},
    {'studies':[{'slug':'a','title':'a','description':'a','category':'a','sources':[{'source_key':'s','title':'a','url':'file:///tmp/test','source_type':'other'}]}]},
    {'relations':[{'from_study_id':'a','to_study_id':'a','relation_type':'similar','source_study_id':'a','source_key':'s','explanation':'a','evidence':{'excerpt':'a'}}]},
    {'relations':[{'from_study_id':'a','to_study_id':'b','relation_type':'similar','source_study_id':'c','source_key':'s','explanation':'a','evidence':{'excerpt':'a'}}]},
])
def test_invalid_package(change):
    with pytest.raises(ValueError):
        Package.model_validate({'schema_version':1,'studies':[],**change})

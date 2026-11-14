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

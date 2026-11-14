import asyncio
from uuid import uuid4
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.database import engine
from app.main import app, rate_windows
from app.repositories import catalog
from app.schemas.ingestion import Package
from app.services.ingestion import import_package


def test_full_import_and_graph():
    async def run():
        async with engine.connect() as connection:
            transaction=await connection.begin()
            factory=async_sessionmaker(connection,expire_on_commit=False,join_transaction_mode='create_savepoint')
            original=catalog.session_factory
            catalog.session_factory=factory
            try:
                prefix='graph-'+uuid4().hex
                slugs=[prefix+'-'+str(i) for i in range(53)]
                studies=[{'slug':slug,'title':slug,'description':'Synthetic test only','category':'test','sources':[{'source_key':'s','title':'test','url':'https://example.com','source_type':'other'}]} for slug in slugs]
                studies[0]['media']=[{'media_key':'m','source_key':'s','media_type':'link','url':'https://example.com','caption':'synthetic'}]
                studies[0]['datasets']=[{'dataset_key':'d','source_key':'s','title':'synthetic','chart_type':'line','x_label':'x','y_label':'y','units':{'x':'s','y':'K'},'series':[{'id':'s','label':'test','points':[{'x':1,'y':None}]}],'provenance':'reported'}]
                links=[{'from_study_id':slugs[0],'to_study_id':slug,'relation_type':'similar','source_study_id':slugs[0],'source_key':'s','explanation':'Synthetic','evidence':{'excerpt':'test'},'verified':True} for slug in slugs[1:51]]
                links.append({**links[0],'from_study_id':slugs[1],'to_study_id':slugs[51],'source_study_id':slugs[1]})
                links.append({**links[0],'to_study_id':slugs[52],'verified':False})
                package=Package.model_validate({'schema_version':1,'studies':studies,'relations':links})
                await import_package(package,factory=factory)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                    r=await client.get('/api/v1/nexus/graph',params={'study_id':slugs[0]})
                    graph=r.json(); assert r.status_code==200, graph
                    assert len(graph['nodes'])==50 and graph['truncated']
                    ids={x['id'] for x in graph['nodes']}
                    assert slugs[52] not in ids
                    assert all(e['source'] in ids and e['target'] in ids for e in graph['edges'])
                    r=await client.get('/api/v1/nexus/graph',params={'study_id':slugs[51],'depth':1})
                    assert {x['id'] for x in r.json()['nodes']}=={slugs[1],slugs[51]}
                    r=await client.get('/api/v1/nexus/graph',params={'study_id':slugs[51],'depth':2})
                    assert {x['id'] for x in r.json()['nodes']}=={slugs[0],slugs[1],slugs[51]}
                    r=await client.get('/api/v1/nexus/graph',params={'study_id':slugs[52]})
                    assert len(r.json()['nodes'])==1 and r.json()['edges']==[]
                    r=await client.get(f'/api/v1/studies/{slugs[0]}/relations'); assert len(r.json())==50
                    for name,count in [('sources',1),('findings',0),('media',1),('datasets',1)]:
                        r=await client.get(f'/api/v1/studies/{slugs[0]}/{name}'); assert r.status_code==200 and len(r.json())==count
                    before=(await client.get(f'/api/v1/studies/{slugs[0]}')).json()
                    await import_package(package,factory=factory)
                    assert (await client.get(f'/api/v1/studies/{slugs[0]}')).json()==before
                    rate_windows.clear()
                    r=await client.post('/api/v1/assistant/compare',json={'study_ids':slugs[:2]}); assert r.status_code==200 and r.json()['status']=='insufficient_evidence'
            finally:
                catalog.session_factory=original
                await transaction.rollback()
        await engine.dispose()
    asyncio.run(run())

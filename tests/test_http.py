import asyncio
import importlib
import httpx
import pytest
from app.main import app, rate_windows


def test_http_contract(monkeypatch):
    async def run():
        rate_windows.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Origin':'http://localhost:5173'}) as client:
            for method,path,body,status in [('GET','/missing',None,404),('POST','/health',None,405),('GET','/api/v1/studies?limit=0',None,422),('POST','/api/v1/assistant/chat',{'message':'  '},422),('POST','/api/v1/assistant/chat',{'message':'hi','scope':'study'},422),('POST','/api/v1/assistant/compare',{'study_ids':['a','a']},422)]:
                r=await client.request(method,path,json=body)
                assert r.status_code==status, r.text
                assert r.json()['error']['request_id']==r.headers['x-request-id']
                assert r.headers['access-control-allow-origin']=='http://localhost:5173'
            r=await client.post('/api/v1/assistant/chat',content=b'x'*32769)
            assert r.status_code==413
            rate_windows.clear()
            for _ in range(5):
                assert (await client.post('/api/v1/assistant/chat',json={'message':'hi'})).status_code==200
            r=await client.post('/api/v1/assistant/chat',json={'message':'hi'})
            assert r.status_code==429 and int(r.headers['retry-after'])>0
            rate_windows.clear()
            r=await client.options('/api/v1/studies',headers={'Access-Control-Request-Method':'GET'})
            assert r.status_code==200 and 'x-request-id' in r.headers
            async def broken(*args):
                raise RuntimeError('secret internal detail')
            monkeypatch.setattr(importlib.import_module('app.repositories.catalog'),'filters',broken)
            r=await client.get('/api/v1/catalog/filters')
            assert r.status_code==500 and 'secret' not in r.text
    asyncio.run(run())

@pytest.mark.parametrize('payload',[
    {'message':'a','history':[{'role':'system','content':'a'}]},
    {'message':'a','history':[{'role':'user','content':'x'*2000}]*7},
    {'message':'a'*2001},
])
def test_chat_validation(payload):
    from app.schemas.assistant import ChatRequest
    with pytest.raises(ValueError):
        ChatRequest.model_validate(payload)

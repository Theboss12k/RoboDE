"""The provider is a standalone function, independent of simulators and editions."""
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import httpx
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.ai_orchestrator.llm import LLMRegistry, ProviderConfiguration
from services.validation.registry import ROOT


@pytest.fixture
def adapter(monkeypatch):
    spec=importlib.util.spec_from_file_location('nebius_example',ROOT/'examples/llm/nebius_token_factory.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for k,v in {'BASE_URL':'https://api.tokenfactory.nebius.com/v1','MODEL':'nvidia/test-nemotron','API_KEY':'private-fixture-key',
                'TIMEOUT':'30','MAX_TOKENS':'1024','RESPONSE_FORMAT':'{"type":"json_object"}'}.items():
        monkeypatch.setenv('ROBOT_IDE_LLM_'+k,v)
    return module


async def test_independent_function_preserves_contract_and_private_settings(adapter,monkeypatch):
    seen=[]
    def respond(request,timeout):
        seen.append((request,timeout))
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"ready":true}','reasoning_content':'excluded'},'finish_reason':'stop'}]}).encode())
    monkeypatch.setattr(adapter.urllib.request,'urlopen',respond)
    assert await adapter.invoke('Input text','Internal instructions')=='{"ready":true}'
    req,timeout=seen[0];payload=json.loads(req.data)
    assert req.full_url=='https://api.tokenfactory.nebius.com/v1/chat/completions' and timeout==30
    assert req.headers['Authorization']=='Bearer private-fixture-key'
    assert payload['messages']==[{'role':'system','content':'Internal instructions'},{'role':'user','content':'Input text'}]
    assert payload['response_format']=={'type':'json_object'} and payload['model']=='nvidia/test-nemotron'
    assert 'private-fixture-key' not in req.data.decode()


@pytest.mark.parametrize('response',[
    {'choices':[{'message':{'content':'partial'},'finish_reason':'length'}]},
    {'choices':[{'message':{'reasoning_content':'not final'},'finish_reason':'stop'}]},
])
async def test_incomplete_or_reasoning_only_response_is_not_an_answer(adapter,monkeypatch,response):
    monkeypatch.setattr(adapter.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(json.dumps(response).encode()))
    with pytest.raises(ValueError):await adapter.invoke('Input','Instructions')


async def test_preset_runs_through_a_separate_worker_and_keeps_both_roles_independent(store):
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append((self.headers.get('Authorization'),body))
            content=json.dumps({'choices':[{'message':{'content':'{"ready":true}'},'finish_reason':'stop'}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        registry=LLMRegistry(store)
        saved=registry.save(ProviderConfiguration(name='Independent Nebius',connection_type='nebius',base_url=f'http://127.0.0.1:{server.server_port}/v1',model='nvidia/test-nemotron',api_key='private-fixture-key',structured_outputs=True))
        assert saved['protocol']=='python_function' and 'async def invoke(' in saved['source_code']
        assert 'system_prompt' not in saved and 'private-fixture-key' not in json.dumps(saved)
        from services.ai_orchestrator.two_stage import save_settings,settings
        from shared.models.robotics import RoleSettings
        save_settings(registry,RoleSettings(planner_adapter_id=saved['id']))
        assert settings(registry).binding_adapter_id is None
        result=await registry.adapter(saved['id'],json_object=True)('The input','The internal prompt')
        assert result['answer']=='{"ready":true}' and result['adapter_id']==saved['id']
        assert seen[0][0]=='Bearer private-fixture-key' and seen[0][1]['response_format']=={'type':'json_object'}
    finally:server.shutdown();server.server_close();thread.join()


def test_named_provider_discovery_reuses_saved_key_without_exposing_it(store,monkeypatch):
    original=httpx.AsyncClient;seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json={'data':[{'id':'nvidia/test-nemotron'}]})
    monkeypatch.setattr('services.ai_orchestrator.llm.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    monkeypatch.delenv('NEBIUS_API_KEY',raising=False)
    with TestClient(create_app(store)) as client:
        missing=client.post('/api/llm/discover',json={'connection_type':'nebius','base_url':'https://api.tokenfactory.nebius.com/v1'})
        assert missing.status_code==422 and 'API key' in missing.text and not seen
        saved=client.post('/api/llm/adapters',json={'name':'Nebius','connection_type':'nebius','base_url':'https://api.tokenfactory.nebius.com/v1','model':'nvidia/test-nemotron','api_key':'private-fixture-key'}).json()
        assert saved['protocol']=='python_function' and saved['has_api_key']
        found=client.post('/api/llm/discover',json={'connection_type':'nebius','base_url':saved['base_url'],'adapter_id':saved['id']})
        assert found.json()['models']==['nvidia/test-nemotron']
        assert seen[-1].headers['Authorization']=='Bearer private-fixture-key'
        assert 'private-fixture-key' not in client.get('/api/llm/adapters').text
        assert client.get('/api/llm/adapters/'+saved['id']+'/status').json()['available']

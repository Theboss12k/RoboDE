"""Gemini/NVIDIA connectors use independent workers; no hosted requests are made."""
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from fastapi.testclient import TestClient
from services.ai_orchestrator.llm import LLMRegistry, ProviderConfiguration, connection_type
from services.api.main import create_app
from services.validation.registry import ROOT

PROVIDERS = [('gemini', 'GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai'),
             ('nvidia', 'NVIDIA_API_KEY', 'https://integrate.api.nvidia.com/v1')]


@pytest.mark.parametrize('kind,environment,url', PROVIDERS)
async def test_named_connector_uses_separate_worker_and_typed_json_hints(store, kind, environment, url):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get('Authorization'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            body = json.dumps({'choices': [{'message': {'content': '{"calls":[]}', 'reasoning_content': 'excluded'}, 'finish_reason': 'stop'}]}).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        registry = LLMRegistry(store)
        profile = registry.save(ProviderConfiguration(name=kind, connection_type=kind,
            base_url=f'http://127.0.0.1:{server.server_port}/v1', model='fixture-model', api_key='fixture-private-key', structured_outputs=True))
        assert profile['protocol'] == 'python_function' and profile['api_key_env'] == environment
        assert 'async def invoke(input: str, system_prompt: str) -> str:' in profile['source_code']
        result = await registry.adapter(profile['id'], json_object=True)('Task text', 'Internal instructions')
        assert result['answer'] == '{"calls":[]}'
        path, authorization, payload = seen[0]
        assert path == '/v1/chat/completions' and authorization == 'Bearer fixture-private-key'
        assert payload['messages'] == [{'role':'system','content':'Internal instructions'}, {'role':'user','content':'Task text'}]
        assert payload['response_format'] == {'type':'json_object'}
        assert 'fixture-private-key' not in json.dumps(registry.snapshot())
    finally:
        server.shutdown(); server.server_close(); thread.join()


@pytest.mark.parametrize('kind,environment,url', PROVIDERS)
def test_discovery_requires_correct_provider_key_and_preserves_defaults(store, monkeypatch, kind, environment, url):
    monkeypatch.delenv(environment, raising=False)
    seen = []
    original = httpx.AsyncClient
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={'data':[{'id':'fixture-model'}]})
    monkeypatch.setattr('services.ai_orchestrator.llm.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with TestClient(create_app(store)) as client:
        first = client.post('/api/llm/adapters', json={'name':'Existing', 'base_url':'http://localhost:11434/v1','model':'local-fixture'}).json()
        missing = client.post('/api/llm/discover', json={'connection_type':kind,'base_url':url})
        assert missing.status_code == 422 and environment in missing.text and not seen
        saved = client.post('/api/llm/adapters', json={'name':kind,'connection_type':kind,'base_url':url,'model':'fixture-model'}).json()
        assert saved['protocol'] == 'python_function' and not saved['has_api_key']
        assert client.get('/api/llm/adapters').json()['default_id'] == first['id']
        status = client.get('/api/llm/adapters/'+saved['id']+'/status').json()
        assert not status['available'] and 'Enter your' in status['message'] and not seen
        monkeypatch.setenv(environment, 'fixture-environment-key')
        found = client.post('/api/llm/discover', json={'connection_type':kind,'base_url':url})
        assert found.json()['models'] == ['fixture-model']
        assert seen[-1].headers['authorization'] == 'Bearer fixture-environment-key'
        # Saving a credential replaces the environment fallback without exposing it.
        client.put('/api/llm/adapters/'+saved['id'], json={'name':kind,'connection_type':kind,'base_url':url,'model':'fixture-model','api_key':'fixture-saved-key'})
        found = client.post('/api/llm/discover', json={'connection_type':kind,'base_url':url,'adapter_id':saved['id']})
        assert found.json()['models'] == ['fixture-model'] and seen[-1].headers['authorization'] == 'Bearer fixture-saved-key'
        assert 'fixture-saved-key' not in client.get('/api/llm/adapters').text
    assert connection_type({'protocol':'chat_completions','connection_type':'openai','base_url':url}) == kind
    assert connection_type({'protocol':'python_function','connection_type':'custom','base_url':url}) == 'custom'


@pytest.mark.parametrize('choice', [
    {'finish_reason':'length', 'message':{'content':'partial'}},
    {'finish_reason':'stop', 'message':{'reasoning_content':'not an answer'}},
    {'finish_reason':'stop', 'message':{'content':''}},
])
async def test_hosted_function_rejects_truncated_or_missing_final_text(monkeypatch, choice):
    spec = importlib.util.spec_from_file_location('hosted_example', ROOT/'examples/llm/hosted_chat.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for key, value in {'BASE_URL':'https://integrate.api.nvidia.com/v1','MODEL':'fixture-model','API_KEY':'fixture-key','TIMEOUT':'10','MAX_TOKENS':'1024'}.items():
        monkeypatch.setenv('ROBOT_IDE_LLM_'+key, value)
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(json.dumps({'choices':[choice]}).encode()))
    with pytest.raises(ValueError): await module.invoke('Task', 'Internal instructions')

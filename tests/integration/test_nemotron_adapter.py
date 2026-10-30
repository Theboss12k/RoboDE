"""Protocol checks for the installable example, without downloading a model."""
import importlib.util
import io
import json

import pytest
from services.validation.registry import ROOT


@pytest.fixture
def nemotron(monkeypatch):
    spec = importlib.util.spec_from_file_location('nemotron_example', ROOT/'examples/llm/ollama_nemotron.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for key, value in {'BASE_URL': 'http://127.0.0.1:11434', 'MODEL': 'nemotron-3-nano:4b-q8_0',
                       'MAX_TOKENS': '4096', 'TIMEOUT': '120'}.items():
        monkeypatch.setenv('ROBOT_IDE_LLM_'+key, value)
    return module


async def test_nemotron_preserves_private_prompt_and_returns_only_final_content(nemotron, monkeypatch):
    requests = []
    def respond(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(json.dumps({'message': {'thinking': 'private reasoning', 'content': '{"status":"ready"}'},
                                      'done_reason': 'stop'}).encode())
    monkeypatch.setattr(nemotron.urllib.request, 'urlopen', respond)
    assert await nemotron.invoke('Test input', 'Private capability instructions') == '{"status":"ready"}'
    request, timeout = requests[0]
    assert request.full_url == 'http://127.0.0.1:11434/api/chat' and timeout == 120
    body = json.loads(request.data)
    assert body['messages'] == [{'role': 'system', 'content': 'Private capability instructions'}, {'role': 'user', 'content': 'Test input'}]
    assert body['think'] is False and body['options']['num_ctx'] == 16384


async def test_mini_respects_its_smaller_context_and_older_protocol(nemotron, monkeypatch):
    monkeypatch.setenv('ROBOT_IDE_LLM_MODEL', 'nemotron-mini:4b')
    def respond(request, timeout):
        body = json.loads(request.data)
        assert body['options']['num_ctx'] == 4096 and 'think' not in body
        return io.BytesIO(b'{"message":{"content":"ready"},"done_reason":"stop"}')
    monkeypatch.setattr(nemotron.urllib.request, 'urlopen', respond)
    assert await nemotron.invoke('Test', '') == 'ready'


@pytest.mark.parametrize('body', [
    {'message': {'content': '{"tasks":[]}'}, 'done_reason': 'length'},
    {'message': {'thinking': 'no final answer'}, 'done_reason': 'stop'},
    {'error': 'model unavailable'},
])
async def test_invalid_or_truncated_answers_are_rejected(nemotron, monkeypatch, body):
    monkeypatch.setattr(nemotron.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(body).encode()))
    with pytest.raises(ValueError):
        await nemotron.invoke('Test', 'Private prompt')


@pytest.mark.parametrize('partial_write', [False, True])
def test_sdk_benchmark_rejects_partial_motion_before_unsupported_set(partial_write):
    from scripts.nemotron_benchmark import audit_sdk_source
    command = ('self.client.move_base(mapped_positions["base_yaw"])\n        ' if partial_write else '')
    source = '''class Transport:
    def __init__(self, client): self.client = client
    def command(self, mapped_positions):
        ''' + command + '''raise NotImplementedError("Joint set is unsupported")
    def get_state(self): return self.client.get_joint_positions()
    def stop(self): self.client.stop()
    def disconnect(self): self.client.close()
'''
    if partial_write:
        with pytest.raises(AssertionError, match='partial motion'):
            audit_sdk_source(source)
    else:
        audit_sdk_source(source)


@pytest.mark.parametrize('feedback', ['self.client.joint_mapping', 'self.client.get_joint_positions(42)'])
def test_sdk_benchmark_rejects_invented_vendor_interface(feedback):
    from scripts.nemotron_benchmark import audit_sdk_source
    source = '''class Transport:
    def __init__(self, client): self.client = client
    def command(self, mapped_positions): raise NotImplementedError("Unsupported")
    def get_state(self): return ''' + feedback + '''
    def stop(self): self.client.stop()
    def disconnect(self): self.client.close()
'''
    with pytest.raises(AssertionError, match='undocumented'):
        audit_sdk_source(source)

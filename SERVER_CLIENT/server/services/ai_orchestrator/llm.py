"""Global, named LLM adapters. Each adapter is an async (input, system_prompt) function."""
import json
import math
import os
import uuid
import time
import re
from typing import Literal
from urllib.parse import urlsplit
import httpx
from pydantic import Field
from shared.models.domain import Contract
from services.api.storage import atomic_json, safe_id


def json_answer(answer: str):
    """Accept JSON or one leading JSON fence with optional trailing review prose."""
    text = answer.strip()
    fence = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```((?:(?!```)[\s\S])*)', text, flags=re.IGNORECASE)
    return json.loads(fence[1] if fence else text)


class ProviderConfiguration(Contract):
    name: str = Field(min_length=1, max_length=100)
    protocol: Literal['chat_completions', 'python_function'] = 'chat_completions'
    source_code: str = Field(default='', max_length=60000)
    base_url: str = Field(max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(default='', max_length=16000)
    timeout_seconds: float = Field(default=60, ge=1, le=300)
    max_tokens: int = Field(default=2048, ge=1, le=16384)
    api_key_env: str = Field(default='', pattern=r'^(?:[A-Za-z_][A-Za-z0-9_]*)?$')
    api_key: str | None = Field(default=None, max_length=8000)
    clear_api_key: bool = False


class Invocation(Contract):
    input: str = Field(min_length=1, max_length=64000)
    system_prompt: str = Field(default='', max_length=32000)


class LLMRegistry:
    def __init__(self, store):
        self.folder = store.runtime / 'llm'
        self.path = self.folder / 'adapters.json'
        self.secrets = self.folder / 'secrets.json'

    def read(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {'default_id': None, 'adapters': []}

    def write(self, data):
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.folder.chmod(0o700)
        atomic_json(self.path, data)
        self.path.chmod(0o600)

    def all(self, *, private=False):
        data = self.read()
        if os.getenv('AI_BASE_URL') and os.getenv('AI_MODEL') and not any(a['id']=='environment' for a in data['adapters']):
            data['adapters'].append({'id':'environment','name':'Environment provider','protocol':'chat_completions',
                'base_url':os.environ['AI_BASE_URL'],'model':os.environ['AI_MODEL'],'system_prompt':'',
                'timeout_seconds':60,'max_tokens':2048,'api_key_env':'AI_API_KEY','version':1,'has_api_key':bool(os.getenv('AI_API_KEY'))})
            if not self.path.exists() and not data['default_id']:
                data['default_id'] = 'environment'
        if not private:
            data['adapters'] = [self.public(a) for a in data['adapters']]
        return data

    @staticmethod
    def public(value):
        return {k: v for k, v in value.items() if k != 'system_prompt'}

    def resolve(self, adapter_id=None):
        data = self.all(private=True)
        adapter_id = adapter_id or data['default_id']
        result = next((a for a in data['adapters'] if a['id']==adapter_id), None)
        if not result:
            raise ValueError('Choose an LLM adapter in Configuration. Custom SDK generation also supports AI_BASE_URL and AI_MODEL.')
        return dict(result)

    def save(self, configuration, adapter_id=None):
        if configuration.protocol == 'python_function':
            from .code_adapter import validate_source
            validate_source(configuration.source_code)
        value = configuration.model_dump(exclude={'api_key','clear_api_key'})
        value['name'], value['model'] = value['name'].strip(), value['model'].strip()
        url = urlsplit(value['base_url'].strip())
        if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Base URL must be an HTTP(S) API root without credentials, query or fragment')
        if not value['name'] or not value['model']:
            raise ValueError('Adapter name and model cannot be blank')
        value['base_url'] = value['base_url'].strip().rstrip('/')
        data = self.all(private=True)
        old = self.resolve(adapter_id) if adapter_id else None
        if old and 'system_prompt' not in configuration.model_fields_set:
            value['system_prompt'] = old.get('system_prompt', '')
        adapter_id = safe_id(adapter_id or uuid.uuid4().hex[:12])
        secrets = json.loads(self.secrets.read_text()) if self.secrets.exists() else {}
        if configuration.clear_api_key:
            secrets.pop(adapter_id, None)
        if configuration.api_key:
            secrets[adapter_id] = configuration.api_key
        value.update(id=adapter_id, version=(old['version']+1 if old else 1), has_api_key=bool(secrets.get(adapter_id) or os.getenv(value['api_key_env'])))
        data['adapters'] = [a for a in data['adapters'] if a['id']!=adapter_id] + [value]
        if not data['default_id']:
            data['default_id'] = adapter_id
        self.write(data)
        # Secrets are deliberately excluded from every public model, snapshot and generated artifact.
        atomic_json(self.secrets, secrets)
        self.secrets.chmod(0o600)
        return self.public(value)

    def delete(self, adapter_id):
        self.resolve(adapter_id)
        if adapter_id == 'environment' and os.getenv('AI_BASE_URL') and os.getenv('AI_MODEL'):
            raise ValueError('Remove AI_BASE_URL / AI_MODEL from .env to remove the environment adapter')
        data = self.all(private=True)
        data['adapters'] = [a for a in data['adapters'] if a['id']!=adapter_id]
        if data['default_id']==adapter_id:
            data['default_id'] = None
        self.write(data)
        if self.secrets.exists():
            secrets = json.loads(self.secrets.read_text()); secrets.pop(adapter_id,None)
            atomic_json(self.secrets,secrets); self.secrets.chmod(0o600)

    def snapshot(self):
        # Include public versions globally, keeping project fingerprints comparable in the UI.
        return self.all()

    def adapter(self, adapter_id=None):
        """Return the function contract used by drafting, SDK generation and run tasks."""
        configuration = self.resolve(adapter_id)
        async def invoke(input: str, system_prompt: str = '') -> dict:
            invocation = Invocation(input=input, system_prompt=system_prompt)
            secret_data = json.loads(self.secrets.read_text()) if self.secrets.exists() else {}
            key = secret_data.get(configuration['id']) or os.getenv(configuration['api_key_env'], '')
            headers = {'Authorization':f'Bearer {key}'} if key else {}
            system = '\n\n'.join(p for p in (configuration.get('system_prompt', ''), invocation.system_prompt) if p)
            messages = ([{'role':'system','content':system}] if system else []) + [{'role':'user','content':invocation.input}]
            started = time.monotonic()
            try:
                if configuration['protocol'] == 'python_function':
                    from .code_adapter import invoke_code
                    answer = await invoke_code(configuration, invocation.input, system, key)
                    body = {}
                else:
                    async with httpx.AsyncClient(timeout=configuration['timeout_seconds'], follow_redirects=False) as client:
                        response = await client.post(configuration['base_url']+'/chat/completions',headers=headers,
                            json={'model':configuration['model'],'temperature':0,'max_tokens':configuration['max_tokens'],'messages':messages})
                        response.raise_for_status()
                        body = response.json()
                    answer = body['choices'][0]['message']['content']
                if not isinstance(answer,str) or not answer.strip() or len(answer)>120000:
                    raise ValueError('Empty or oversized answer')
                usage = body.get('usage')
                usage = {k:v for k,v in usage.items() if isinstance(v,(int,float)) and math.isfinite(v)} if isinstance(usage,dict) else {}
                return {'answer':answer,'adapter_id':configuration['id'],'adapter_version':configuration['version'],
                    'model':configuration['model'],'duration_seconds':round(time.monotonic()-started,3),'usage':usage}
            except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError,OSError) as error:
                # Never expose response bodies or authorization headers in errors.
                raise ValueError(f"LLM adapter {configuration['name']}: request failed or returned an invalid answer; check endpoint, model, credentials and timeout") from error
        return invoke

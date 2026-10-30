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
from shared.models.robotics import SceneImage


class TruncatedAnswer(ValueError):
    pass


def json_answer(answer: str):
    """Accept JSON or exactly one JSON fence, optionally introduced by a line of prose and followed by review prose.

    Reasoning models (e.g. Nemotron) may prefix one complete <think> block; an unclosed one is truncation."""
    text = re.sub(r'^\s*<think>[\s\S]*?</think>', '', answer, count=1).strip()
    fence = re.fullmatch(r'(?:[^`{\[]*\n)?```(?:json)?\s*\n([\s\S]*?)\n```((?:(?!```)[\s\S])*)', text, flags=re.IGNORECASE)
    return json.loads(fence[1] if fence else text)


class ProviderConfiguration(Contract):
    connection_type: Literal['ollama', 'openai', 'nebius', 'gemini', 'nvidia', 'custom'] | None = None
    structured_outputs: bool = False
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
    supports_vision: bool = False


class Invocation(Contract):
    input: str = Field(min_length=1, max_length=64000)
    system_prompt: str = Field(default='', max_length=32000)
    images: list[SceneImage] = Field(default_factory=list, max_length=2)


def connection_type(configuration):
    """Explicit choice, or inferred for profiles saved before connection types existed."""
    if configuration.get('connection_type') not in {None, 'openai'}:
        return configuration['connection_type']
    if configuration.get('protocol') == 'python_function':
        return configuration.get('connection_type') or 'custom'
    url = urlsplit(configuration.get('base_url', ''))
    hosted = {'generativelanguage.googleapis.com': 'gemini', 'integrate.api.nvidia.com': 'nvidia'}
    if url.hostname in hosted:
        return hosted[url.hostname]
    if configuration.get('connection_type'):
        return configuration['connection_type']
    return 'ollama' if url.port == 11434 or 'ollama' in (url.hostname or '') else 'openai'


def checked_url(base_url):
    url = urlsplit(base_url.strip())
    if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Base URL must be an HTTP(S) API root without credentials, query or fragment')
    return base_url.strip().rstrip('/')


async def discover_models(kind, base_url, key=''):
    """List the models a backend reports. Read-only: never pulls, loads or replaces a model."""
    root = checked_url(base_url)
    from .presets import HOSTED_PROVIDERS
    if kind in HOSTED_PROVIDERS and not key:
        name, environment, _ = HOSTED_PROVIDERS[kind]
        raise ValueError(f'Enter your {name} API key, or configure {environment} on the RoboDE server')
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            if kind == 'ollama':
                response = await client.get(re.sub(r'/v1$', '', root)+'/api/tags')
                response.raise_for_status()
                return sorted({m['name'] for m in response.json().get('models', []) if isinstance(m, dict) and m.get('name')})
            response = await client.get(root+'/models', headers={'Authorization':f'Bearer {key}'} if key else {})
            response.raise_for_status()
            return sorted({m['id'] for m in response.json().get('data', []) if isinstance(m, dict) and m.get('id')})
    except httpx.HTTPStatusError as error:
        raise ValueError(f'The connection answered HTTP {error.response.status_code}; check the URL and API key') from error
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('Could not reach this connection or read its model list') from error


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
        from .presets import provider_preset
        configuration = provider_preset(configuration)
        if configuration.protocol == 'python_function':
            from .code_adapter import validate_source
            validate_source(configuration.source_code, vision=configuration.supports_vision)
        value = configuration.model_dump(exclude={'api_key','clear_api_key'})
        value['name'], value['model'] = value['name'].strip(), value['model'].strip()
        if not value['name'] or not value['model']:
            raise ValueError('Adapter name and model cannot be blank')
        value['base_url'] = checked_url(value['base_url'])
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

    def key(self, adapter_id):
        configuration = self.resolve(adapter_id)
        secrets = json.loads(self.secrets.read_text()) if self.secrets.exists() else {}
        return secrets.get(configuration['id']) or os.getenv(configuration.get('api_key_env') or '', '')

    async def status(self, adapter_id):
        """Whether the profile's model is currently offered; unavailable profiles stay configured."""
        configuration = self.resolve(adapter_id)
        kind = connection_type(configuration)
        if kind == 'custom':
            return {'available': None, 'connection_type': kind, 'models': [],
                    'message': 'Custom functions cannot list models. Use Test model to check this profile.'}
        try:
            models = await discover_models(kind, configuration['base_url'], self.key(adapter_id))
        except ValueError as error:
            return {'available': False, 'connection_type': kind, 'models': [], 'message': str(error)}
        if not models:
            return {'available': None, 'connection_type': kind, 'models': [],
                    'message': 'This connection does not list its models. Use Test model to check this profile.'}
        if configuration['model'] in models:
            return {'available': True, 'connection_type': kind, 'models': models, 'message': 'Model available on this connection'}
        return {'available': False, 'connection_type': kind, 'models': models,
                'message': f"{configuration['model']} is not offered by this connection. The profile is kept; choose another model or make it available on the backend."}

    def snapshot(self):
        # Include public versions globally, keeping project fingerprints comparable in the UI.
        return self.all()

    def adapter(self, adapter_id=None, response_schema=None, json_object=False):
        """Return the function contract used by drafting, SDK generation and run tasks."""
        configuration = self.resolve(adapter_id)
        async def invoke(input: str, system_prompt: str = '', images=None) -> dict:
            invocation = Invocation(input=input, system_prompt=system_prompt, images=images or [])
            if invocation.images and not configuration.get('supports_vision'):
                raise ValueError('VLM mode requires a vision-capable LLM adapter; select one or explicitly disable VLM')
            secret_data = json.loads(self.secrets.read_text()) if self.secrets.exists() else {}
            key = secret_data.get(configuration['id']) or os.getenv(configuration['api_key_env'], '')
            headers = {'Authorization':f'Bearer {key}'} if key else {}
            system = '\n\n'.join(p for p in (configuration.get('system_prompt', ''), invocation.system_prompt) if p)
            messages = ([{'role':'system','content':system}] if system else []) + [{'role':'user','content':invocation.input}]
            if invocation.images:
                messages[-1]['content']=[{'type':'text','text':invocation.input},*[{'type':'image_url','image_url':{'url':f'data:{im.mime_type};base64,{im.data_base64}'}} for im in invocation.images]]
            started = time.monotonic()
            try:
                finish_reason = None
                if configuration['protocol'] == 'python_function':
                    from .code_adapter import invoke_code
                    answer = await invoke_code(configuration, invocation.input, system, key, [im.model_dump() for im in invocation.images],
                                               response_schema=response_schema, json_object=json_object)
                    body = {}
                else:
                    async with httpx.AsyncClient(timeout=configuration['timeout_seconds'], follow_redirects=False) as client:
                        payload={'model':configuration['model'],'temperature':0,'max_tokens':configuration['max_tokens'],'messages':messages}
                        if response_schema and configuration.get('structured_outputs'):
                            payload['response_format']={'type':'json_schema','json_schema':{'name':'robode_response','schema':response_schema,'strict':False}}
                        elif json_object and configuration.get('structured_outputs'):
                            # Nested planner schemas use $defs, which some local grammar converters reject; plain JSON mode is portable.
                            payload['response_format']={'type':'json_object'}
                        response = await client.post(configuration['base_url']+'/chat/completions',headers=headers,json=payload)
                        response.raise_for_status()
                        body = response.json()
                    choice = body['choices'][0]
                    answer, finish_reason = choice['message']['content'], choice.get('finish_reason')
                    if finish_reason == 'length':
                        raise TruncatedAnswer('Output reached the token limit')
                if not isinstance(answer,str) or not answer.strip() or len(answer)>120000:
                    raise ValueError('Empty or oversized answer')
                if re.match(r'\s*<think>', answer) and '</think>' not in answer:
                    raise TruncatedAnswer('Reasoning never reached a final answer')
                usage = body.get('usage')
                usage = {k:v for k,v in usage.items() if isinstance(v,(int,float)) and math.isfinite(v)} if isinstance(usage,dict) else {}
                return {'answer':answer,'adapter_id':configuration['id'],'adapter_version':configuration['version'],
                    'model':configuration['model'],'provider_host':urlsplit(configuration['base_url']).hostname,
                    'finish_reason':finish_reason,'duration_seconds':round(time.monotonic()-started,3),'usage':usage}
            except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError,OSError) as error:
                # Never expose response bodies or authorization headers in errors.
                reason = ('output reached its token limit; no partial answer was used. Increase max tokens or shorten the request'
                          if isinstance(error, TruncatedAnswer) else
                          'request failed or returned an invalid answer; check endpoint, model, credentials and timeout')
                raise ValueError(f"LLM adapter {configuration['name']}: {reason}") from error
        return invoke

"""Global provider configuration and the explicit input/system-prompt/answer API."""
from typing import Literal
import os
from fastapi import APIRouter
from pydantic import Field
from shared.models.domain import Contract
from services.ai_orchestrator.llm import ProviderConfiguration, Invocation, discover_models

class DefaultAdapter(Contract):
    adapter_id: str | None


class Discovery(Contract):
    connection_type: Literal['ollama', 'openai', 'nebius', 'gemini', 'nvidia']
    base_url: str = Field(max_length=1000)
    api_key: str | None = Field(default=None, max_length=8000)
    adapter_id: str | None = None
    api_key_env: str = Field(default='', pattern=r'^(?:[A-Za-z_][A-Za-z0-9_]*)?$')


def llm_router(registry, controller, controls):
    router = APIRouter(prefix='/api/llm')
    def idle():
        if controller.leases or controls.sessions:
            raise ValueError('Stop runs and close controls before changing global LLM adapters')

    @router.get('/adapters')
    async def adapters():
        return registry.all()

    @router.post('/adapters',status_code=201)
    async def create(data:ProviderConfiguration):
        idle()
        return registry.save(data)

    @router.put('/adapters/{adapter_id}')
    async def edit(adapter_id:str,data:ProviderConfiguration):
        idle()
        return registry.save(data,adapter_id)

    @router.delete('/adapters/{adapter_id}')
    async def delete(adapter_id:str):
        idle(); registry.delete(adapter_id)
        return {'deleted':True}

    @router.put('/default')
    async def default(data:DefaultAdapter):
        idle()
        if data.adapter_id:
            registry.resolve(data.adapter_id)
        value=registry.all(private=True); value['default_id']=data.adapter_id
        registry.write(value)
        return registry.all()

    @router.post('/discover')
    async def discover(data:Discovery):
        # A saved profile's key is reused server-side so it never returns to the browser.
        from services.ai_orchestrator.presets import HOSTED_PROVIDERS
        preset=HOSTED_PROVIDERS.get(data.connection_type)
        key=data.api_key or (registry.key(data.adapter_id) if data.adapter_id else '') or os.getenv(data.api_key_env or (preset[1] if preset else ''), '')
        return {'models':await discover_models(data.connection_type,data.base_url,key)}

    @router.get('/adapters/{adapter_id}/status')
    async def status(adapter_id:str):
        return await registry.status(adapter_id)

    @router.post('/adapters/{adapter_id}/invoke')
    async def invoke(adapter_id:str,data:Invocation):
        return await registry.adapter(adapter_id)(data.input,data.system_prompt,images=data.images)

    return router

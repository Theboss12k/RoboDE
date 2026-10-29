"""Global provider configuration and the explicit input/system-prompt/answer API."""
from fastapi import APIRouter
from shared.models.domain import Contract
from services.ai_orchestrator.llm import ProviderConfiguration, Invocation

class DefaultAdapter(Contract):
    adapter_id: str | None


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

    @router.post('/adapters/{adapter_id}/invoke')
    async def invoke(adapter_id:str,data:Invocation):
        return await registry.adapter(adapter_id)(data.input,data.system_prompt)

    return router

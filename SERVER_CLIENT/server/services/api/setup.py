"""First-boot setup: simulator, compute target and AI model, saved per edition."""
import json
import secrets
from typing import Literal
from fastapi import APIRouter
from pydantic import Field
from shared.models.domain import Contract, now
from services.api.storage import atomic_json
from services.api.edition import DEFAULTS, TOKEN_FACTORY_URL, edition, setup_path


class FirstBootSetup(Contract):
    simulator: Literal['isaac_sim', 'builtin']
    compute: Literal['nebius', 'gcp', 'local', 'remote'] = 'nebius'
    nebius_host: str = Field(default='', max_length=255)
    nebius_ssh_user: str = Field(default='ubuntu', max_length=64)
    ssh_key_file: str = Field(default='', max_length=4096)
    worker_token: str | None = Field(default=None, max_length=4096)
    ai: Literal['token_factory', 'ollama', 'existing', 'skip'] = 'skip'
    ai_model: str = Field(default='', max_length=200)
    # Optional separate Task LLM on the same connection; empty uses ai_model for both roles.
    ai_task_model: str = Field(default='', max_length=200)
    ai_api_key: str | None = Field(default=None, max_length=8000)
    ollama_url: str = Field(default='http://localhost:11434/v1', max_length=1000)


def saved(store):
    path = setup_path(store)
    return json.loads(path.read_text()) if path.exists() else None


def preferred_simulator(store):
    """Simulator for new projects: the saved choice, else the edition default.
    None keeps the source project's simulator (the standard build before any setup)."""
    value = saved(store)
    if value is None and edition() == 'standard':
        return None
    value = value or DEFAULTS[edition()]
    return 'isaac_sim' if value.get('simulator') == 'isaac_sim' else 'mock'


def setup_router(store, controller, controls):
    router = APIRouter(prefix='/api/setup')

    def public():
        value = saved(store)
        return {'edition': edition(), 'completed': bool(value and value.get('completed')), 'defaults': DEFAULTS[edition()], 'saved': value}

    @router.get('')
    async def get():
        return public()

    @router.put('')
    async def save(data: FirstBootSetup):
        from services.api.isaac import IsaacConfiguration, save_configuration, worker_configuration
        from services.ai_orchestrator.llm import ProviderConfiguration
        if controller.leases or controls.sessions or any(s.remote for s in controller.sessions.values()):
            raise ValueError('Stop runs, close controls and disconnect Isaac before changing setup')
        # Validate everything before writing anything, so a rejected setup changes nothing.
        isaac = None
        if data.simulator == 'isaac_sim':
            current = worker_configuration(store)
            token = data.worker_token or current.get('token') or secrets.token_urlsafe(32)
            isaac = IsaacConfiguration(**{**{k: v for k, v in current.items() if k in IsaacConfiguration.model_fields},
                'deployment': data.compute, 'token': token, 'on_demand': False if data.compute != 'gcp' else current.get('on_demand', False),
                **({'url': 'http://127.0.0.1:9100', 'nebius_host': data.nebius_host.strip(), 'nebius_ssh_user': data.nebius_ssh_user.strip() or 'ubuntu',
                    'ssh_key_file': data.ssh_key_file.strip()} if data.compute == 'nebius' else {}),
                **({'url': 'http://127.0.0.1:9100'} if data.compute == 'local' else {})})
        profile = None
        if data.ai == 'token_factory':
            existing = next((a for a in controller.llm.all()['adapters'] if a.get('base_url', '').rstrip('/') == TOKEN_FACTORY_URL and a['model'] == data.ai_model), None)
            if not data.ai_model.strip():
                raise ValueError('Choose a Nemotron model available to your Token Factory key')
            if not data.ai_api_key and not (existing and existing.get('has_api_key')):
                raise ValueError('Enter your Nebius Token Factory API key, or choose Skip and add it later in AI Models')
            profile = (existing, ProviderConfiguration(name=f'Nebius Token Factory · {data.ai_model.strip()}'[:100], connection_type='nebius',
                base_url=TOKEN_FACTORY_URL, model=data.ai_model.strip(), api_key=data.ai_api_key or None, timeout_seconds=120, max_tokens=4096, structured_outputs=True))
        elif data.ai == 'ollama':
            if not data.ai_model.strip():
                raise ValueError('Choose an Ollama model')
            profile = (None, ProviderConfiguration(name=f'Ollama · {data.ai_model.strip()}'[:100], connection_type='ollama', base_url=data.ollama_url,
                model=data.ai_model.strip(), structured_outputs=True, timeout_seconds=120, max_tokens=4096))
        if isaac:
            await controller.gpu.close()
            await controller.nebius.close()
            save_configuration(store, isaac.model_dump())
        if profile:
            from services.ai_orchestrator.two_stage import save_settings, settings
            existing, configuration = profile
            value = controller.llm.save(configuration, existing['id'] if existing else None)
            data_value = controller.llm.all(private=True)
            data_value['default_id'] = value['id']
            controller.llm.write(data_value)
            task_id = None
            task_model = data.ai_task_model.strip()
            if task_model and task_model != configuration.model:
                twin = next((a for a in controller.llm.all()['adapters'] if a.get('base_url', '').rstrip('/') == configuration.base_url.rstrip('/') and a['model'] == task_model), None)
                # The Task LLM reuses the planner connection's key when none is entered for it.
                key = data.ai_api_key or (controller.llm.key(value['id']) if configuration.connection_type == 'nebius' else None)
                task = configuration.model_copy(update={'name': configuration.name.replace(configuration.model, task_model)[:100], 'model': task_model, 'api_key': key or None})
                task_id = controller.llm.save(task, twin['id'] if twin else None)['id']
            roles = settings(controller.llm)
            save_settings(controller.llm, roles.model_copy(update={'planner_adapter_id': value['id'], 'binding_adapter_id': task_id or value['id']}))
        choices = data.model_dump(exclude={'ai_api_key', 'worker_token'})
        atomic_json(setup_path(store), {**choices, 'edition': edition(), 'completed': True, 'completed_at': now()})
        return public()

    return router

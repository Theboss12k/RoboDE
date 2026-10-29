"""Opt-in real Ollama QA runtime, isolated from saved user projects and hardware.

Run with scripts/python.mjs; serves API 18877, IDE 18878, Business 18879.
The transparent local relay records actual Ollama responses for review.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from contextlib import nullcontext

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, Request, Response
from services.api.main import create_app
from services.api.storage import Storage, atomic_json
from services.ai_orchestrator.llm import LLMRegistry, ProviderConfiguration
from services.validation.registry import ROOT
from web.gateway import create_gateway


async def main():
    evidence = Path(os.environ.get('OLLAMA_QA_EVIDENCE', 'artifacts/ollama-20261029')).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    model = os.environ.get('OLLAMA_QA_MODEL', 'phi4:14b')
    calls_path = evidence / 'ollama-calls.json'
    records = json.loads(calls_path.read_text()) if calls_path.exists() else []
    relay = FastAPI()

    @relay.post('/v1/chat/completions')
    async def completion(request: Request):
        body = await request.json()
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post('http://127.0.0.1:11434/v1/chat/completions', json=body)
        record = {'request': body, 'status': response.status_code,
                  'duration_seconds': round(time.monotonic() - started, 3), 'response': response.json()}
        records.append(record)
        atomic_json(evidence / 'ollama-calls.json', records)
        print(f"Ollama call {len(records)}: HTTP {response.status_code}, {record['duration_seconds']}s", flush=True)
        return Response(response.content, status_code=response.status_code, media_type='application/json')

    retained=os.environ.get('OLLAMA_QA_DATA_DIR')
    with (nullcontext(retained) if retained else tempfile.TemporaryDirectory(prefix='robot-real-ollama-')) as directory:
        root = Path(directory).resolve()
        for pid in ['electron', 'browser', 'business', 'capabilities']:
            target = root / 'projects' / pid
            if (target/'project.yaml').exists():continue
            target.mkdir(parents=True)
            for folder in ['robots', 'environment']:
                shutil.copytree(ROOT / 'examples/projects/apple_transfer' / folder, target / folder)
            project = yaml.safe_load((ROOT / 'examples/projects/apple_transfer/project.yaml').read_text())
            project.update(id=pid, name=f'Phi-4 {pid} QA', robots=['robots/arm_01/instance.yaml'], simulation={'adapter':'mock'})
            project.pop('workflow_tasks', None)
            project.pop('default_goals', None)
            (target / 'project.yaml').write_text(yaml.safe_dump(project))
            shutil.copyfile(ROOT / 'robot_system/registry/models/demo_arm/instances/instance.yaml', target / 'robots/arm_01/instance.yaml')
        store = Storage(root)
        atomic_json(store.runtime / 'connections/isaac.json', {'deployment':'remote'})
        registry=LLMRegistry(store)
        provider=next((p for p in registry.all()['adapters'] if p['model']==model),None) or registry.save(ProviderConfiguration(name='Ollama Phi-4 functional QA',
            base_url='http://127.0.0.1:18880/v1', model=model, timeout_seconds=300, max_tokens=4096))
        atomic_json(evidence / 'runtime.json', {'model':model, 'provider_id':provider['id'], 'data_root':str(root), 'code':'ollama-functional-qa'})
        runtime = create_app(store, speed=150)
        transport = httpx.ASGITransport(app=runtime)
        apps = [(runtime,18877), (create_gateway(code='ollama-functional-qa',scope='ide',transport=transport),18878),
                (create_gateway(code='ollama-functional-qa',scope='business',transport=transport),18879), (relay,18880)]
        servers = [uvicorn.Server(uvicorn.Config(app, host='127.0.0.1',port=port,log_level='warning')) for app,port in apps]
        await asyncio.gather(*(server.serve() for server in servers))


if __name__ == '__main__':
    asyncio.run(main())

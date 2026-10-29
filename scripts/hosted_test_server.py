"""Isolated production-gateway browser fixture; user projects are never modified."""
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import tempfile
import httpx
import uvicorn
import yaml
from services.api.main import create_app
from services.api.storage import Storage,atomic_json
from services.validation.registry import ROOT
from web.gateway import create_gateway

with tempfile.TemporaryDirectory(prefix='robot-hosted-test-') as directory:
    # Normalize macOS /var → /private/var before cloning project components.
    root=Path(directory).resolve();target=root/'projects/apple_transfer';target.mkdir(parents=True)
    for name in ('robots','environment'):shutil.copytree(ROOT/'examples/projects/apple_transfer'/name,target/name)
    project=yaml.safe_load((ROOT/'examples/projects/apple_transfer/project.yaml').read_text());project.update(robots=['robots/arm_01/instance.yaml'],simulation={'adapter':'mock'});project.pop('workflow_tasks',None);project.pop('default_goals',None)
    (target/'project.yaml').write_text(yaml.safe_dump(project))
    shutil.copyfile(ROOT/'robot_system/registry/models/demo_arm/instances/instance.yaml',target/'robots/arm_01/instance.yaml')
    store=Storage(root)
    atomic_json(store.runtime/'connections/isaac.json',{'deployment':'remote'})
    runtime=create_app(store,speed=100)
    from scripts.contract_scene import ContractScene,connect_factory
    runtime.state.controller.remote_factory=connect_factory(ContractScene())
    gateway=create_gateway(code='hosted-browser-test-code',scope='ide',transport=httpx.ASGITransport(app=runtime))
    gateway_lifespan=gateway.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        async with runtime.router.lifespan_context(runtime),gateway_lifespan(app):yield
    gateway.router.lifespan_context=lifespan
    uvicorn.run(gateway,host='127.0.0.1',port=8082)

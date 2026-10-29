"""Private, disposable demonstration data for recorded product walkthroughs."""
import asyncio
from contextlib import nullcontext
import copy
import hashlib
import json
from pathlib import Path
import shutil
import signal
import zipfile

import httpx
import uvicorn
import yaml
from services.api.main import create_app
from services.api.storage import Storage, atomic_json
from services.ai_orchestrator.llm import LLMRegistry, ProviderConfiguration
from services.adapters.generation import AdapterRegistry
from services.validation.registry import ROOT
from web.gateway import create_gateway

OUT=Path('artifacts/walkthroughs').resolve()


async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    root=OUT/'demo-data'
    if root.exists():shutil.rmtree(root)
    for variant in ['desktop','web']:
        for suffix,source in [('', 'apple_transfer'),('_dual','dual_arm_cell')]:
            pid=variant+suffix;target=root/'projects'/pid
            shutil.copytree(ROOT/'examples/projects'/source,target)
            project=yaml.safe_load((target/'project.yaml').read_text())
            project.update(id=pid,name=('Desktop' if variant=='desktop' else 'Server')+(' · dual robot cell' if suffix else ' · training workspace'),simulation={'adapter':'mock'})
            (target/'project.yaml').write_text(yaml.safe_dump(project))
    business=root/'projects/business'
    shutil.copytree(ROOT/'examples/projects/apple_transfer',business)
    project=yaml.safe_load((business/'project.yaml').read_text())
    project.update(id='business',name='Operations · sample workspace',simulation={'adapter':'mock'})
    (business/'project.yaml').write_text(yaml.safe_dump(project))
    world={'frame':'world','units':'m','objects':[
        dict(id='apple',name='Apple',kind='object',position=dict(x=.34,y=-.16,z=.0525),size=dict(x=.065,y=.065,z=.065),mass_kg=.08),
        dict(id='table1',name='Table1',kind='obstacle',position=dict(x=.34,y=-.16,z=.01),size=dict(x=.14,y=.14,z=.02),mass_kg=0),
        dict(id='table2',name='Table2',kind='obstacle',position=dict(x=.27,y=.27,z=.01),size=dict(x=.18,y=.18,z=.02),mass_kg=0)]}
    (business/'environment/world.yaml').write_text(yaml.safe_dump(world))
    store=Storage(root)
    atomic_json(store.runtime/'connections/isaac.json',{'deployment':'remote','url':'http://127.0.0.1:19999','gcp_project':'','gcp_zone':'','gcp_instance':''})
    llm=LLMRegistry(store)
    provider=llm.save(ProviderConfiguration(name='Local Ollama · Phi-4',base_url='http://127.0.0.1:11434/v1',model='phi4:14b',timeout_seconds=300,max_tokens=4096))
    config=llm.all();config['default_id']=None;llm.write(config)
    prior=Path('artifacts/ollama-20261029/phi-4-browser-sdk.bundle.json')
    if prior.exists():
        bundle=json.loads(prior.read_text());bundle['name']='Previously generated Phi-4 SDK draft'
        AdapterRegistry(store).save(bundle)
    # A sample imported USDZ exposes alignment controls without reconstruction or deployment.
    roomdir=store.runtime/'rooms/business/example_scan';roomdir.mkdir(parents=True)
    with zipfile.ZipFile(roomdir/'scene.usdz','w',compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('sample.usda','#usda 1.0\n( metersPerUnit = 1 upAxis = "Z" )\ndef Xform "IllustrativeRoom" { def Cube "RoomBounds" { double size = 4 } }\n')
    atomic_json(roomdir/'room.json',{'id':'example_scan','name':'Sample imported room · feature preview','status':'align','photos':0,'stage':'Example USDZ · not a scanned room','source':'imported_usdz','sha256':hashlib.sha256((roomdir/'scene.usdz').read_bytes()).hexdigest()})
    draftdir=store.runtime/'rooms/business/example_capture';draftdir.mkdir(parents=True)
    atomic_json(draftdir/'room.json',{'id':'example_capture','name':'Room capture · feature preview','status':'capture','photos':0,'stage':'No photos recorded','source':'demonstration'})
    (OUT/'sample-part.obj').write_text('v -1 -1 -1\nv 1 -1 -1\nv 0 1 -1\nv 0 0 1\nf 1 2 3\nf 1 4 2\nf 2 4 3\nf 3 4 1\n')
    atomic_json(OUT/'runtime.json',{'provider_id':provider['id'],'data_root':str(root),'code':'walkthrough-demo-code'})
    runtime=create_app(store,speed=2)
    transport=httpx.ASGITransport(app=runtime)
    apps=[(runtime,19877),(create_gateway(code='walkthrough-demo-code',scope='ide',transport=transport),19878),
          (create_gateway(code='walkthrough-demo-code',scope='business',transport=transport),19879)]
    servers=[uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning')) for app,port in apps]
    for server in servers:server.capture_signals=lambda:nullcontext()
    def stop():
        for server in servers:server.should_exit=True
    loop=asyncio.get_running_loop()
    for sig in [signal.SIGTERM,signal.SIGINT]:loop.add_signal_handler(sig,stop)
    await asyncio.gather(*(server.serve() for server in servers))


if __name__=='__main__':asyncio.run(main())

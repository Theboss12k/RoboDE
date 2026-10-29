"""Disposable recording workspace using the operator's real GCP Isaac worker."""
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import signal

import httpx
import uvicorn
import yaml
from services.api.main import create_app
from services.api.storage import Storage,atomic_json
from services.validation.registry import ROOT
from web.gateway import create_gateway

OUT=Path(os.getenv('ROBOT_IDE_RECORDING_DIR','artifacts/gcp-recording-20261029')).resolve()

async def main():
    OUT.mkdir(parents=True,exist_ok=True);OUT.chmod(0o700)
    root=OUT/'data'
    if root.exists():raise ValueError('Recording data already exists; preserve it or choose a fresh recording directory.')
    target=root/'projects/gcp_demo'
    shutil.copytree(ROOT/'examples/projects/dual_arm_cell',target)
    project=yaml.safe_load((target/'project.yaml').read_text())
    project.update(id='gcp_demo',name='NVIDIA GCP · demonstration',simulation={'adapter':'mock'},
        default_prompt='Move home.',default_goals=[{'id':'home_a','robot_id':'arm_01','prompt':'Move home.','dependencies':[]},
            {'id':'home_b','robot_id':'arm_02','prompt':'Move home.','dependencies':[]}])
    (target/'project.yaml').write_text(yaml.safe_dump(project))
    for index,rid in enumerate(['arm_01','arm_02']):
        path=target/f'robots/{rid}/instance.yaml';instance=yaml.safe_load(path.read_text())
        instance['base_pose']={'x':0.,'y':index*1.4,'z':0.,'yaw':0.}
        instance['initial_configuration']['actuator_positions']={'base_yaw':0.,'shoulder':1.,'elbow':-1.8,'wrist':.8,'gripper':.08}
        path.write_text(yaml.safe_dump(instance))
    world={'frame':'world','units':'m','objects':[
        dict(id='apple',name='Apple',kind='object',position=dict(x=.34,y=-.16,z=.2325),size=dict(x=.065,y=.065,z=.065),mass_kg=.08),
        dict(id='table1',name='Table1',kind='obstacle',position=dict(x=.34,y=-.16,z=.1),size=dict(x=.14,y=.14,z=.2),mass_kg=0),
        dict(id='table2',name='Table2',kind='obstacle',position=dict(x=.27,y=.27,z=.1),size=dict(x=.18,y=.18,z=.2),mass_kg=0)]}
    (target/'environment/world.yaml').write_text(yaml.safe_dump(world))
    store=Storage(root)
    config=json.loads((ROOT/'robot_system/runtime/connections/isaac.json').read_text())
    if config.get('deployment')!='gcp' or not config.get('on_demand'):raise ValueError('Configure the real on-demand GCP worker first.')
    if os.getenv('ROBOT_IDE_RECORDING_ATTACHED')=='1':
        # A separately supervised lifecycle owns the already-running GPU/tunnel.
        config['on_demand']=False
    else:config['url']='http://127.0.0.1:19100'
    file=store.runtime/'connections/isaac.json';atomic_json(file,config);file.chmod(0o600);file.parent.chmod(0o700)
    runtime=create_app(store,speed=1)
    requested=False
    @runtime.middleware('http')
    async def record_start(request,call_next):
        nonlocal requested
        if request.method=='POST' and request.url.path=='/api/configuration/isaac/gpu/start':requested=True
        return await call_next(request)
    gateway=create_gateway(code='gcp-recording-demo-code',scope='ide',transport=httpx.ASGITransport(app=runtime))
    servers=[uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning')) for app,port in [(runtime,19887),(gateway,19888)]]
    for server in servers:server.capture_signals=lambda:nullcontext()
    def stop():
        for server in servers:server.should_exit=True
    loop=asyncio.get_running_loop()
    for sig in [signal.SIGTERM,signal.SIGINT]:loop.add_signal_handler(sig,stop)
    try:await asyncio.gather(*(server.serve() for server in servers))
    finally:
        if requested:
            try:await runtime.state.controller.gpu.stop()
            except Exception as error:
                print('Recording shutdown needs verification: '+str(error),flush=True)

if __name__=='__main__':asyncio.run(main())

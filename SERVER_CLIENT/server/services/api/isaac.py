"""Remote Isaac endpoint configuration. Tokens stay in owner-only runtime storage."""
import json
import os
import sys
import secrets
from typing import Literal
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter
from pydantic import Field,model_validator
from shared.models.domain import Contract
from services.api.storage import atomic_json
from shared.models.worker import PROTOCOL


class IsaacConfiguration(Contract):
    deployment:Literal['local','gcp','remote']='remote'
    url:str=Field(default='http://127.0.0.1:9100',max_length=2048)
    token:str|None=Field(default=None,max_length=4096)
    load_scene:bool=False
    gcp_project:str=Field(default='',pattern=r'^[a-zA-Z0-9_-]*$',max_length=100)
    gcp_zone:str=Field(default='',pattern=r'^[a-zA-Z0-9_-]*$',max_length=100)
    gcp_instance:str=Field(default='',pattern=r'^[a-zA-Z0-9_-]*$',max_length=100)

    on_demand:bool=False
    idle_minutes:int=Field(default=10,ge=1,le=120)
    max_session_minutes:int=Field(default=120,ge=10,le=480)
    use_iap:bool=True
    ssh_key_file:str=Field(default='',max_length=4096)
    local_launcher:str=Field(default='',max_length=4096)
    local_source:str=Field(default='',max_length=4096)
    local_source_kind:Literal['automatic','catalog','manifest']='automatic'
    local_gui:bool=True

    @model_validator(mode='after')
    def endpoint(self):
        parsed=urlsplit(self.url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
            raise ValueError('Use an HTTP(S) worker origin without credentials, query or path')
        if parsed.scheme=='http' and parsed.hostname not in {'localhost','127.0.0.1','::1'}:
            raise ValueError('Use HTTPS for a remote worker or HTTP through a loopback SSH tunnel')
        if self.token is not None and len(self.token)<16:raise ValueError('Worker token requires at least 16 characters')
        if self.on_demand and not all((self.gcp_project,self.gcp_zone,self.gcp_instance)):raise ValueError('Set project, zone and VM name for on-demand GPU')
        if self.deployment!='gcp' and self.deployment!='remote' and self.on_demand:raise ValueError('Local Isaac cannot start a GCP VM')
        if self.deployment=='local' and (parsed.scheme!='http' or parsed.hostname!='127.0.0.1'):raise ValueError('Local Isaac uses http://127.0.0.1:PORT')
        if any(ch in self.local_launcher+self.local_source+self.ssh_key_file for ch in '\r\n\0'):raise ValueError('Use paths without control characters')
        if self.ssh_key_file:
            from pathlib import Path
            if not Path(self.ssh_key_file).is_absolute():raise ValueError('SSH key file must be an absolute path on the IDE server')
        self.url=self.url.rstrip('/')
        return self


def worker_configuration(store):
    path=store.runtime/'connections/isaac.json'
    saved=json.loads(path.read_text()) if path.exists() else {}
    # Legacy manually configured endpoints remain attach-only; never acquire a
    # local process or change cloud billing behavior as a side effect of upgrading.
    if saved or os.getenv('ISAAC_WORKER_URL') or os.getenv('ISAAC_WORKER_TOKEN'):
        deployment=saved.get('deployment') or ('gcp' if saved.get('on_demand') or saved.get('gcp_project') else 'remote')
    else:deployment='gcp' if sys.platform=='darwin' else 'local'
    return {'deployment':deployment,'local_launcher':'','local_source':'','local_source_kind':'automatic','local_gui':True,
        'url':os.getenv('ISAAC_WORKER_URL','http://127.0.0.1:9100'),'token':os.getenv('ISAAC_WORKER_TOKEN',''),
        'load_scene':deployment=='local','gcp_project':'','gcp_zone':'','gcp_instance':'','on_demand':False,'idle_minutes':10,'max_session_minutes':120,'use_iap':True,'ssh_key_file':'',**saved}


def isaac_router(store,controller,controls):
    router=APIRouter(prefix='/api/configuration/isaac')
    def public():
        data=worker_configuration(store)
        return {k:v for k,v in data.items() if k!='token'}|{'has_token':bool(data.get('token'))}
    @router.get('')
    async def get():return public()
    @router.put('')
    async def save(data:IsaacConfiguration):
        if controller.resources.owners or controller.leases or controls.sessions or any(s.remote for s in controller.sessions.values()) or (controller.gpu.task and not controller.gpu.task.done()) or controller.local_isaac.running() or (controller.local_isaac.task and not controller.local_isaac.task.done()):
            raise ValueError('Disconnect Isaac and close active controls before changing the worker connection')
        updated=data.model_dump();updated['token']=data.token or worker_configuration(store)['token']
        if len(updated['token'])<16:raise ValueError('Set the worker token before saving')
        await controller.gpu.close()
        path=store.runtime/'connections/isaac.json';path.parent.mkdir(parents=True,exist_ok=True);path.parent.chmod(0o700)
        atomic_json(path,updated);path.chmod(0o600)
        return public()
    @router.get('/setup')
    async def setup():
        from integrations.local_isaac import host_capabilities
        return host_capabilities()
    @router.post('/token')
    async def token():
        # Return only the new draft; saving is explicit and never exposes a saved secret.
        return {'token':secrets.token_urlsafe(32)}
    @router.get('/local')
    async def local_status():return controller.local_isaac.snapshot()
    @router.get('/local/log')
    async def local_log():return {'text':controller.local_isaac.log_tail()}
    @router.post('/local/check')
    async def local_check():
        controller.local_isaac.check()
        return {'message':'Launcher, scene source, token and loopback endpoint are configured. Start Isaac to check the native GPU runtime.'}
    @router.post('/local/start',status_code=202)
    async def local_start():
        if controller.leases or controls.sessions or controller.resources.owners:raise ValueError('Stop active plans and close manual controls before launching Isaac.')
        return await controller.local_isaac.start()
    @router.post('/local/stop')
    async def local_stop():
        for pid in controller.sessions:controller.recordings.guard(pid)
        if controller.leases or controls.sessions or controller.resources.owners:raise ValueError('Stop active plans and close manual controls before stopping Isaac.')
        for pid,session in list(controller.sessions.items()) if controller.local_isaac.running() else []:
            if session.remote:
                states=await controller.states(session)
                await controller.disconnect(pid)
                controller.offline[pid]=(session,{rid:s.model_copy(update={'connected':False}) for rid,s in states.items()})
        return await controller.local_isaac.stop()
    @router.get('/gpu')
    async def gpu_status(refresh:bool=False):return await controller.gpu.snapshot(refresh)
    @router.post('/gpu/start',status_code=202)
    async def gpu_start():return controller.gpu.request_start()
    @router.post('/gpu/stop')
    async def gpu_stop():
        for pid in controller.sessions:controller.recordings.guard(pid)
        if controller.leases or controls.sessions or controller.resources.owners:raise ValueError('Stop active plans and close manual controls before stopping the GPU VM.')
        # Reconstruction is checked by the worker: never abandon a running GPU job.
        import os
        url=os.getenv('NUREC_WORKER_URL','http://127.0.0.1:9200');token=os.getenv('NUREC_WORKER_TOKEN','')
        if token:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response=await client.get(url+'/v1/health',headers={'Authorization':'Bearer '+token});response.raise_for_status()
                    if response.json().get('active_jobs',0):raise ValueError('Wait for reconstruction to finish or cancel it before stopping the GPU.')
            except httpx.HTTPError as error:raise ValueError('Cannot confirm reconstruction is idle. Use Google Cloud Console to inspect the VM.') from error
        for pid,session in list(controller.sessions.items()):
            if session.remote:await controller.disconnect(pid)
        return await controller.gpu.stop()

    @router.post('/probe')
    async def probe():
        config=worker_configuration(store)
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response=await client.get(config['url']+'/v1/health',headers={'Authorization':'Bearer '+config['token']})
                response.raise_for_status();data=response.json()
            except (httpx.HTTPError,ValueError) as error:
                raise ValueError('Worker probe failed. Check the SSH tunnel, saved token and worker process.') from error
        if data.get('protocol')!=PROTOCOL or data.get('engine')!='isaac_sim':raise ValueError('Worker is not a compatible native Isaac Sim backend')
        return data
    return router

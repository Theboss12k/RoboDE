"""Authenticated, single-cell worker. Native physics is injected by the standalone launcher."""
import asyncio
import contextlib
import secrets
import os
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse
from shared.models.worker import PROTOCOL, ConnectRequest, StepRequest, ResetRequest, SceneObjectsRequest
from services.validation.registry import validate_positions


def create_worker(backend, token: str, lease_seconds=20):
    if len(token) < 16:
        raise ValueError('ISAAC_WORKER_TOKEN must contain at least 16 characters')
    lease = {'id':None,'project':None,'last':0.,'sequence':0}
    lock = asyncio.Lock()

    def end_recording():
        if backend.metadata.get('scene_recording'):
            backend.recording_end_session()

    async def reap():
        while True:
            await asyncio.sleep(1)
            async with lock:
                if lease['id'] and time.monotonic()-lease['last'] > lease_seconds:
                    end_recording()
                    backend.stop()
                    lease['id'] = None

    @asynccontextmanager
    async def lifespan(app):
        job = asyncio.create_task(reap())
        yield
        job.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await job
        end_recording()
        backend.stop()

    from integrations.gcp.activity import touch,guard_status,idle_seconds
    app = FastAPI(title='Robot IDE Isaac Sim Worker',lifespan=lifespan)
    async def auth(authorization: str=Header(default='')):
        if not secrets.compare_digest(authorization,f'Bearer {token}'):
            raise HTTPException(401,'Invalid worker token')
    app.router.dependencies.append(Depends(auth))
    @app.exception_handler(ValueError)
    async def invalid(request,error):
        return JSONResponse({'detail':str(error)},status_code=422)

    def owned(session_id):
        if lease['id'] and time.monotonic()-lease['last'] > lease_seconds:
            end_recording()
            backend.stop()
            lease['id'] = None
        if lease['id'] != session_id:
            raise HTTPException(409,'Worker lease expired or belongs to another session; reconnect and replan')
        lease['last'] = time.monotonic()

    def observation():
        data = backend.observe()
        data['sequence'] = lease['sequence']
        return data

    @app.get('/v1/health')
    async def health():
        from integrations.gcp.cloud_apps import links
        return {'protocol':PROTOCOL,**backend.metadata,'idle_guard_active':guard_status(),'idle_timeout_seconds':idle_seconds(),
                'instance_id':os.getenv('ROBOT_IDE_ISAAC_INSTANCE'),'cloud_apps':links(),
                'cloud_apps_installed':os.getenv('ROBOT_IDE_CLOUD_APPS')=='1'}

    @app.post('/v1/sessions')
    async def connect(data:ConnectRequest):
        async with lock:
            if lease['id'] and time.monotonic()-lease['last']>lease_seconds:
                end_recording();backend.stop();lease['id']=None
            if lease['id']:
                raise HTTPException(409,'GPU cell is already leased; disconnect its existing project first')
            if data.transfer_positions is not None:
                if not data.load_scene:raise ValueError('Scene transfer requires managed scene loading')
                models={r['instance']['instance']['id']:r['model'] for r in data.robots}
                if set(data.transfer_positions)!=set(models):raise ValueError('Scene transfer must include every robot')
                for rid,q in data.transfer_positions.items():validate_positions(models[rid],q)
            touch('isaac')
            if data.load_scene:
                if not backend.metadata.get('scene_loading'):raise ValueError('Worker has no approved robot asset catalog')
                touch('isaac');backend.load_scene(data)
            backend.validate_scene(data)
            if data.transfer_positions is not None:
                # Initializing a newly transferred simulator scene is explicit;
                # normal attach does not reset joints or overwrite a running scene.
                backend.reset(data.transfer_positions,data.objects)
            lease.update(id=uuid.uuid4().hex,project=data.project_id,last=time.monotonic(),sequence=0)
            # Connect reads the existing scene; never applies saved initial positions.
            return {'session_id':lease['id'],'observation':observation()}

    @app.put('/v1/scene-assets/meshes/{digest}')
    async def mesh_asset(digest:str,request:Request,format:str):
        import hashlib,re
        from pathlib import Path
        from services.api.assets import validate_asset,FORMATS,MAX_ASSET_BYTES
        from services.api.rooms import stream_file
        async with lock:
            if not backend.metadata.get('asset_uploading') or not getattr(backend,'mesh_root',None):raise ValueError('Update the managed worker to transfer imported meshes')
            if not re.fullmatch(r'[a-f0-9]{64}',digest) or format not in FORMATS:raise ValueError('Invalid mesh checksum or format')
            folder=Path(backend.mesh_root)/digest;folder.mkdir(parents=True,exist_ok=True)
            temporary=folder/(uuid.uuid4().hex+'.tmp')
            try:
                await stream_file(request,temporary,MAX_ASSET_BYTES,progress=lambda:touch('isaac'))
                data=temporary.read_bytes()
                if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Mesh checksum mismatch')
                validate_asset(data,format)
                path=folder/('model.'+format)
                temporary.replace(path)
                touch('isaac')
                return backend.register_mesh(path,digest)
            finally:temporary.unlink(missing_ok=True)

    @app.put('/v1/scene-assets/rooms/{digest}')
    async def project_room(digest:str,request:Request):
        async with lock:
            return await store_room(digest,request)

    @app.get('/v1/sessions/{session_id}/state')
    async def state(session_id:str):
        async with lock:
            owned(session_id)
            return observation()

    @app.get('/v1/sessions/{session_id}/assets')
    async def assets(session_id:str):
        async with lock:
            owned(session_id)
            if not hasattr(backend,'inventory'):raise ValueError('Update the native worker to list all scene assets')
            return backend.inventory()

    @app.put('/v1/sessions/{session_id}/room-assets/{digest}')
    async def room_asset(session_id:str,digest:str,request:Request):
        async with lock:
            owned(session_id)
            return await store_room(digest,request)

    async def store_room(digest,request):
        import hashlib
        import re
        import uuid
        from pathlib import Path
        if not backend.metadata.get('room_loading') or not getattr(backend,'room_root',None):raise ValueError('Managed room uploads are not enabled on this worker')
        if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('Invalid room checksum')
        from services.api.rooms import stream_file,validate_usdz,MAX_SCENE
        folder=Path(backend.room_root)/digest;folder.mkdir(parents=True,exist_ok=True)
        temporary=folder/(uuid.uuid4().hex+'.usdz')
        try:
            await stream_file(request,temporary,MAX_SCENE,progress=lambda:touch('isaac'))
            if hashlib.sha256(temporary.read_bytes()).hexdigest()!=digest:raise ValueError('Room checksum mismatch')
            validate_usdz(temporary);path=folder/'scene.usdz';temporary.replace(path)
            touch('isaac')
            return backend.register_room(path,digest)
        finally:temporary.unlink(missing_ok=True)

    @app.post('/v1/sessions/{session_id}/step')
    async def step(session_id:str,data:StepRequest):
        async with lock:
            owned(session_id)
            if data.sequence != lease['sequence']+1:
                raise HTTPException(409,'Duplicate or out-of-order physics tick')
            if set(data.positions) != set(backend.models):
                raise ValueError('Every physics tick must command the complete cell atomically')
            for rid,q in data.positions.items():
                validate_positions(backend.models[rid],q)
            touch('isaac');backend.advance(data.positions,data.dt)
            lease['sequence'] = data.sequence
            return observation()

    @app.put('/v1/sessions/{session_id}/objects')
    async def objects(session_id:str,data:SceneObjectsRequest):
        async with lock:
            owned(session_id)
            if not backend.metadata.get('scene_editing'):raise ValueError('This worker uses a fixed scene')
            if not all(s['stopped'] for s in backend.observe()['states'].values()):raise ValueError('Stop every robot before editing the native scene')
            touch('isaac');backend.sync_objects(data.objects)
            return observation()

    @app.put('/v1/sessions/{session_id}/scene')
    async def scene(session_id:str,data:ConnectRequest):
        async with lock:
            owned(session_id)
            if data.project_id!=lease['project']:raise ValueError('Scene belongs to another project')
            if not data.load_scene or not backend.metadata.get('scene_loading'):raise ValueError('Managed scene loading is required')
            if {r['instance']['instance']['id'] for r in data.robots}!=set(backend.models):raise ValueError('Scene robot set changed; reconnect first')
            if not all(s['stopped'] for s in backend.observe()['states'].values()):raise ValueError('Stop every robot before replacing the scene')
            touch('isaac');backend.load_scene(data)
            backend.validate_scene(data)
            return observation()

    @app.post('/v1/sessions/{session_id}/reset')
    async def reset(session_id:str,data:ResetRequest):
        async with lock:
            owned(session_id)
            if set(data.positions) != set(backend.models):
                raise ValueError('Reset must include every robot')
            for rid,q in data.positions.items():
                validate_positions(backend.models[rid],q)
            touch('isaac');backend.reset(data.positions,data.objects)
            return observation()

    @app.post('/v1/sessions/{session_id}/stop')
    async def stop(session_id:str):
        async with lock:
            owned(session_id)
            backend.stop()
            return observation()

    @app.delete('/v1/sessions/{session_id}')
    async def disconnect(session_id:str):
        async with lock:
            owned(session_id)
            try:
                end_recording()
                backend.stop()
            finally:lease['id'] = None
            return {'disconnected':True}
    def recording_supported():
        if not backend.metadata.get('scene_recording'):
            raise ValueError('Update the native Isaac worker to enable scene recording')

    @app.post('/v1/sessions/{session_id}/recordings', status_code=201)
    async def recording_start(session_id:str, data:dict):
        from shared.models.recording import RecordingRequest
        async with lock:
            owned(session_id)
            recording_supported()
            settings=RecordingRequest.model_validate(data)
            touch('isaac-recording')
            record=backend.recording_start(lease['project'],session_id,settings.model_dump(mode='json'))
            lease['last']=time.monotonic()
            return record

    @app.post('/v1/sessions/{session_id}/recordings/{record_id}/stop')
    async def recording_stop(session_id:str,record_id:str):
        async with lock:
            owned(session_id)
            recording_supported()
            record=backend.recording_get(lease['project'],record_id)
            if record['status'] in {'recording','finalizing'}:
                return backend.recording_stop()
            return record

    @app.get('/v1/sessions/{session_id}/recordings')
    async def recordings(session_id:str):
        async with lock:
            owned(session_id)
            recording_supported()
            return backend.recording_list(lease['project'])

    @app.get('/v1/recordings/{record_id}')
    async def recording_status(record_id:str,project_id:str):
        async with lock:
            recording_supported()
            # An active owner's polls renew its lease, without booting a VM or
            # moving robots. Historical downloads require worker auth only.
            if lease['id'] and lease['project']==project_id:
                owned(lease['id'])
            return backend.recording_get(project_id,record_id)

    @app.get('/v1/recordings/{record_id}/file')
    async def recording_file(record_id:str,project_id:str):
        async with lock:
            recording_supported()
            path=backend.recording_file(project_id,record_id)
            return FileResponse(path,media_type='video/mp4',filename='RoboDE-scene-'+record_id+'.mp4')

    return app

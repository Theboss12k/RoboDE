"""Separate real-room capture/reconstruction/alignment workflow, with explicit native deployment."""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import uuid
import zipfile
import httpx
from fastapi import APIRouter,Request,HTTPException
from pydantic import Field
from shared.models.domain import Contract,Pose,WorldObject,now
from services.api.storage import atomic_json,safe_id

MAX_SCENE=1024*1024*1024

class NewRoom(Contract):
    name:str=Field(min_length=1,max_length=100)

class RoomAlignment(Contract):
    metres_per_unit:float=Field(gt=0,le=10000)
    translation:Pose
    yaw_degrees:float=Field(ge=-360,le=360)
    reviewed:bool
    assets:list[WorldObject]=Field(min_length=1,max_length=128)


def validate_usdz(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if not entries or len(entries)>10000 or sum(i.file_size for i in entries)>4*MAX_SCENE:raise ValueError('USDZ package is empty or too large.')
            if any(i.filename.startswith(('/','\\')) or '..' in Path(i.filename.replace('\\','/')).parts or (i.external_attr>>16)&0o170000==0o120000 for i in entries):raise ValueError('USDZ contains an unsafe path or symbolic link.')
            if not any(Path(i.filename).suffix.lower() in {'.usd','.usda','.usdc'} for i in entries):raise ValueError('The package has no USD scene.')
    except zipfile.BadZipFile as error:raise ValueError('Upload the reconstructed .usdz package, not a photo archive.') from error


async def stream_file(request,path,limit,progress=None):
    count=0
    try:
        with path.open('wb') as handle:
            async for chunk in request.stream():
                count+=len(chunk)
                if count>limit:raise HTTPException(413,'File exceeds the upload limit.')
                handle.write(chunk)
                if progress:progress()
        if not count:raise ValueError('The uploaded file is empty.')
    except BaseException:path.unlink(missing_ok=True);raise


def rooms_router(store,controller,controls):
    router=APIRouter(prefix='/api/business')
    locks={}
    def root(pid):store.load_project(pid);return store.runtime/'rooms'/safe_id(pid)
    def folder(pid,rid):
        p=root(pid)/safe_id(rid)
        if not (p/'room.json').exists():raise FileNotFoundError('Unknown room capture')
        return p
    def read(pid,rid):return json.loads((folder(pid,rid)/'room.json').read_text())
    def save(pid,rid,data):atomic_json(folder(pid,rid)/'room.json',data)
    def config():
        url=os.getenv('NUREC_WORKER_URL','').rstrip('/');token=os.getenv('NUREC_WORKER_TOKEN','')
        if not url or len(token)<24:raise ValueError('Room reconstruction is not connected yet. Your photos can be saved now. Ask your administrator to connect GPU processing, or import a reconstructed room.')
        from urllib.parse import urlsplit
        p=urlsplit(url)
        if p.scheme not in {'http','https'} or p.username or p.password or p.query or p.fragment or p.path not in {'','/'}:raise ValueError('Use a worker origin without credentials or a path.')
        if p.scheme=='http' and p.hostname not in {'localhost','127.0.0.1','::1'}:raise ValueError('Use HTTPS or a loopback SSH tunnel for the reconstruction worker.')
        return url,token
    async def remote(method,path,**kwargs):
        url,token=config()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response=await client.request(method,url+path,headers={'Authorization':'Bearer '+token},**kwargs)
                response.raise_for_status();return response.json()
        except httpx.HTTPStatusError as error:
            try:message=error.response.json()['detail']
            except (ValueError,KeyError):message='Reconstruction worker rejected the request.'
            raise ValueError(str(message)) from error
        except httpx.HTTPError as error:raise ValueError('The reconstruction worker is unavailable. Check its tunnel and service.') from error
    @router.get('/rooms/status')
    async def worker_status():
        if controller.gpu.enabled() and controller.gpu.state['status']!='ready':return {'ready':False,'message':'GPU is stopped. Start GPU processing when you are ready to reconstruct; photo capture does not need it.','cloud':await controller.gpu.snapshot()}
        try:
            result=await remote('GET','/v1/health')
            if result.get('protocol')!='robot-ide.nurec.v1':raise ValueError('Incompatible reconstruction worker.')
            return result
        except ValueError as error:return {'ready':False,'message':str(error)}
    @router.post('/projects/{pid}/rooms/import-capture',status_code=201)
    async def import_capture(pid:str,request:Request):
        import shutil,re
        directory=root(pid);directory.mkdir(parents=True,exist_ok=True)
        rid=uuid.uuid4().hex;temporary=directory/('.upload-'+rid+'.zip');target=directory/rid
        await stream_file(request,temporary,512*1024*1024)
        try:
            with zipfile.ZipFile(temporary) as archive:
                entries=archive.infolist();names=[e.filename for e in entries]
                if len(entries)>501 or len(names)!=len(set(names)) or sum(e.file_size for e in entries)>512*1024*1024:raise ValueError('Capture archive exceeds its limits or has duplicate entries')
                if 'capture.json' not in names or archive.getinfo('capture.json').file_size>65536:raise ValueError('Missing capture manifest')
                if any(e.flag_bits&1 or e.compress_type not in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED} or (e.external_attr>>16)&0o170000==0o120000 or not (e.filename=='capture.json' or re.fullmatch(r'photos/[A-Za-z0-9_-]+[.](?:jpg|jpeg|png)',e.filename)) for e in entries):raise ValueError('Capture archive contains an unsafe or unsupported path')
                manifest=json.loads(archive.read('capture.json'))
                if not isinstance(manifest,dict) or manifest.get('format')!='robot-room-capture-v1':raise ValueError('Unsupported room capture format')
                name=NewRoom(name=manifest.get('name','Room capture')).name
                photos=[e for e in entries if e.filename!='capture.json']
                if not photos or any(e.file_size>12*1024*1024 for e in photos):raise ValueError('Include at least one JPEG/PNG photo, each under 12 MB')
                (target/'photos').mkdir(parents=True)
                for entry in photos:
                    content=archive.read(entry)
                    if not (content.startswith(b'\xff\xd8\xff') or content.startswith(b'\x89PNG\r\n\x1a\n')):raise ValueError('Capture contains an invalid photograph')
                    (target/entry.filename).write_bytes(content)
            data={'id':rid,'name':name,'status':'capture','photos':len(photos),'created_at':now(),'stage':'Imported photos · reconstruction required','error':None,'source':'offline_capture'}
            atomic_json(target/'room.json',data);return data
        except (zipfile.BadZipFile,KeyError,json.JSONDecodeError) as error:
            shutil.rmtree(target,ignore_errors=True);raise ValueError('Invalid room capture ZIP') from error
        except BaseException:
            shutil.rmtree(target,ignore_errors=True);raise
        finally:temporary.unlink(missing_ok=True)

    @router.get('/projects/{pid}/rooms')
    async def rooms(pid:str):return [json.loads(p.read_text()) for p in sorted(root(pid).glob('*/room.json'),key=lambda p:p.stat().st_mtime,reverse=True)]
    @router.post('/projects/{pid}/rooms',status_code=201)
    async def create(pid:str,data:NewRoom):
        rid=uuid.uuid4().hex;path=root(pid)/rid;path.mkdir(parents=True)
        result={'id':rid,'name':data.name.strip(),'status':'capture','photos':0,'created_at':now(),'stage':'Add room photographs','error':None}
        atomic_json(path/'room.json',result);return result
    @router.put('/projects/{pid}/rooms/{rid}/photos',status_code=201)
    async def photo(pid:str,rid:str,request:Request,filename:str):
        async with locks.setdefault((pid,rid),asyncio.Lock()):
            data=read(pid,rid)
            if data['status'] not in {'capture','failed','cancelled'}:raise ValueError('Start a new capture to upload more photographs.')
            data.update(status='capture',error=None,stage='Add room photographs')
            ext=Path(filename).suffix.lower()
            if ext not in {'.jpg','.jpeg','.png'}:raise ValueError('Use JPG or PNG photographs.')
            directory=folder(pid,rid)/'photos';directory.mkdir(exist_ok=True)
            if len(list(directory.iterdir()))>=500:raise ValueError('Use at most 500 photographs per room.')
            path=directory/(uuid.uuid4().hex+ext)
            await stream_file(request,path,12*1024*1024)
            signature=path.read_bytes()[:8]
            if not(signature.startswith(b'\xff\xd8\xff') or signature.startswith(b'\x89PNG\r\n\x1a\n')):path.unlink();raise ValueError('This file is not a JPEG or PNG photograph.')
            if sum(p.stat().st_size for p in directory.iterdir())>512*1024*1024:path.unlink();raise ValueError('Capture photographs exceed 512 MB.')
            data['photos']=len(list(directory.iterdir()));save(pid,rid,data);return data
    @router.put('/projects/{pid}/rooms/{rid}/scene')
    async def import_scene(pid:str,rid:str,request:Request):
        async with locks.setdefault((pid,rid),asyncio.Lock()):
            data=read(pid,rid)
            if data['status'] not in {'capture','failed','cancelled'}:raise ValueError('Create a new room capture before replacing an existing reconstruction.')
            path=folder(pid,rid)/'upload.usdz';await stream_file(request,path,MAX_SCENE)
            try:validate_usdz(path)
            except BaseException:path.unlink(missing_ok=True);raise
            target=path.with_name('scene.usdz');path.replace(target)
            data.update(status='align',stage='Calibrate scale and name room assets',sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size,source='imported_usdz')
            save(pid,rid,data);return data
    @router.post('/projects/{pid}/rooms/{rid}/reconstruct',status_code=202)
    async def reconstruct(pid:str,rid:str):
        async with locks.setdefault((pid,rid),asyncio.Lock()):
            data=read(pid,rid)
            if data['status'] not in {'capture','failed','cancelled'}:raise ValueError('This room is already submitted. Start a new capture or cancel its reconstruction.')
            files=list((folder(pid,rid)/'photos').glob('*'))
            if len(files)<12:raise ValueError('Add at least 12 overlapping room photographs before reconstructing.')
            archive=io.BytesIO()
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as package:
                for p in files:package.write(p,p.name)
            await controller.gpu.ensure_running()
            result=await remote('POST','/v1/jobs',content=archive.getvalue())
            data.update(status='reconstructing',worker_job=result['id'],stage=result.get('stage','Queued for GPU'),error=None)
            save(pid,rid,data);return data
    @router.get('/projects/{pid}/rooms/{rid}')
    async def progress(pid:str,rid:str):
        async with locks.setdefault((pid,rid),asyncio.Lock()):
            data=read(pid,rid)
            if data['status']=='reconstructing':
                result=await remote('GET','/v1/jobs/'+safe_id(data['worker_job']))
                data.update(stage=result.get('stage','Reconstructing'),error=result.get('error'))
                if result['status'] in {'failed','cancelled'}:data['status']=result['status']
                if result['status']=='ready':
                    url,token=config();path=folder(pid,rid)/'download.usdz'
                    try:
                        async with httpx.AsyncClient(timeout=180) as client:
                            async with client.stream('GET',url+'/v1/jobs/'+data['worker_job']+'/artifact',headers={'Authorization':'Bearer '+token}) as response:
                                response.raise_for_status();count=0
                                with path.open('wb') as handle:
                                    async for chunk in response.aiter_bytes():
                                        count+=len(chunk)
                                        if count>MAX_SCENE:raise ValueError('Reconstructed scene exceeds 1 GB.')
                                        handle.write(chunk)
                        validate_usdz(path);digest=hashlib.sha256(path.read_bytes()).hexdigest()
                        if digest!=result['sha256']:raise ValueError('Reconstructed scene checksum did not match the worker.')
                        path.replace(path.with_name('scene.usdz'))
                    except BaseException:path.unlink(missing_ok=True);raise
                    data.update(status='align',sha256=digest,bytes=count,stage='Calibrate scale and name room assets',source='colmap_3dgrut')
                save(pid,rid,data)
            return data
    @router.delete('/projects/{pid}/rooms/{rid}/reconstruction')
    async def cancel(pid:str,rid:str):
        async with locks.setdefault((pid,rid),asyncio.Lock()):
            data=read(pid,rid)
            if data['status']!='reconstructing':raise ValueError('No active reconstruction to cancel.')
            await remote('DELETE','/v1/jobs/'+data['worker_job']);data.update(status='cancelled',stage='Cancelled');save(pid,rid,data);return data
    @router.get('/projects/{pid}/rooms/{rid}/scene')
    async def download(pid:str,rid:str):
        from fastapi.responses import FileResponse
        path=folder(pid,rid)/'scene.usdz'
        if not path.is_file():raise HTTPException(409,'The reconstructed scene is not ready.')
        return FileResponse(path,media_type='model/vnd.usdz+zip',filename='room.usdz')
    @router.post('/projects/{pid}/rooms/{rid}/deploy')
    async def deploy(pid:str,rid:str,data:RoomAlignment):
        controller.recordings.guard(pid)
        async with locks.setdefault((pid,rid),asyncio.Lock()):
            from services.execution.resources import environment_resource
            from services.api.storage import component
            import yaml
            record=read(pid,rid)
            if record['status'] not in {'align','deployed'}:raise ValueError('Complete or import a reconstruction before deploying it.')
            if not data.reviewed:raise ValueError('Review metric scale, floor alignment and the named collision proxies first.')
            if any(s['project_id']==pid for s in controls.sessions.values()):raise ValueError('Close robot controls before changing the room.')
            controller.ensure_idle(pid)
            project,_,_,cell,_=await controller.context(pid)
            if not cell.remote or not cell.remote.metadata.get('room_loading'):raise ValueError('Connect a managed Isaac Sim worker with room loading enabled. Room reconstruction remains available without it.')
            ids=[o.id for o in data.assets]
            if len(set(ids))!=len(ids) or len({o.name.casefold().strip() for o in data.assets})!=len(ids):raise ValueError('Give every room asset a unique ID and name.')
            if any(o.mesh for o in data.assets):raise ValueError('Room proxies use named boxes; the USDZ provides the room visuals.')
            old_room=store.project_folder(pid)/'environment/room.json'
            previous_room=old_room.read_text() if old_room.exists() else None
            previous_proxy_ids=set(json.loads(previous_room).get('proxy_ids',[])) if previous_room else set()
            objects=[o for o in cell.objects if o.id not in previous_proxy_ids]
            if set(ids)&({o.id for o in objects}|set(cell.instances)):raise ValueError('A room proxy ID conflicts with an existing asset or robot.')
            if {o.name.strip().casefold() for o in data.assets}&{o.name.strip().casefold() for o in objects}:raise ValueError('A room asset name conflicts with an existing workspace asset.')
            objects+=data.assets
            from simulation.isaac_sim.scene_assets import validate_objects
            validate_objects(objects,{o.mesh.asset_id:True for o in objects if o.mesh})
            if any(o.position.z-o.size.z/2<-.001 for o in data.assets):raise ValueError('Room proxies must be on or above the floor.')
            owner='room:'+uuid.uuid4().hex;controller.resources.acquire([environment_resource(pid,cell.backend)],owner)
            world_path=component(store.project_folder(pid),project['environment']);previous_world=world_path.read_text()
            try:
                states=await controller.states(cell)
                if any(not s.stopped for s in states.values()) or any(cell.held_objects.values()):raise ValueError('Stop all robots and release held objects before replacing the room.')
                reference={'asset_id':record['sha256'],'name':record['name'],'metres_per_unit':data.metres_per_unit,'translation':data.translation.model_dump(),'yaw_degrees':data.yaw_degrees}
                await cell.remote.upload_room(folder(pid,rid)/'scene.usdz',record['sha256'])
                await cell.remote.reconfigure(list(cell.instances.values()),cell.models,objects,{k:s.positions for k,s in states.items()},room=reference)
                world=yaml.safe_load(previous_world);world['objects']=[o.model_dump(mode='json',exclude_none=True) for o in objects]
                world_path.write_text(yaml.safe_dump(world,sort_keys=False))
                atomic_json(old_room,{**reference,'proxy_ids':ids,'capture_id':rid})
                cell.objects=cell.remote.latest.objects
                record.update(status='deployed',stage='Available in Isaac Sim',alignment=data.model_dump(),deployed_at=now());save(pid,rid,record)
                return record
            except BaseException:
                world_path.write_text(previous_world)
                if previous_room is None:old_room.unlink(missing_ok=True)
                else:old_room.write_text(previous_room)
                controller.sessions.pop(pid,None)
                await cell.remote.disconnect()
                raise
            finally:controller.resources.release(owner)
    return router

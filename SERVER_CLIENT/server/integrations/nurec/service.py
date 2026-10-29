"""Authenticated GPU reconstruction worker using NVIDIA's COLMAP + 3DGUT workflow.
Run inside the configured CUDA/3dgrut environment; no shell/user-provided code.
"""
import asyncio
import contextlib
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import shutil
import signal
from integrations.gcp.activity import touch,guard_status
import sys
import uuid
import zipfile
from fastapi import FastAPI,Request,HTTPException,Depends
from fastapi.responses import FileResponse
from services.api.storage import atomic_json

MAX_UPLOAD=512*1024*1024

def create_worker(root=None,token=None,grut_root=None):
    root=Path(root or os.getenv('NUREC_JOBS_ROOT','artifacts/nurec-jobs')).resolve();root.mkdir(parents=True,exist_ok=True)
    token=token or os.getenv('NUREC_WORKER_TOKEN','')
    if len(token)<24:raise ValueError('Set NUREC_WORKER_TOKEN to at least 24 characters')
    grut=Path(grut_root or os.getenv('THREEDGRUT_ROOT','/opt/3dgrut')).resolve()
    jobs={};semaphore=asyncio.Semaphore(1)
    @contextlib.asynccontextmanager
    async def lifespan(app):
        for path in root.glob('*/job.json'):
            data=json.loads(path.read_text())
            if data['status'] in {'queued','reconstructing'}:data.update(status='failed',error='Worker restarted. Start a new reconstruction.');atomic_json(path,data)
        pulse=asyncio.create_task(heartbeat())
        yield
        pulse.cancel()
        with contextlib.suppress(asyncio.CancelledError):await pulse
        for job in jobs.values():
            job['cancel']=True
            if job.get('process') and job['process'].returncode is None:await halt(job['process'])
        await asyncio.gather(*(j['task'] for j in jobs.values()),return_exceptions=True)
    app=FastAPI(title='Robot Workspace NuRec GPU worker',lifespan=lifespan)
    async def auth(request:Request):
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+token):raise HTTPException(401,'Invalid reconstruction worker token')
    app.router.dependencies.append(Depends(auth))
    def directory(key):
        if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise HTTPException(404,'Unknown reconstruction')
        path=root/key
        if not (path/'job.json').exists():raise HTTPException(404,'Unknown reconstruction')
        return path
    def status(folder,**changes):
        path=folder/'job.json';data=json.loads(path.read_text()) if path.exists() else {};data.update(changes);atomic_json(path,data);return data
    def ready():return shutil.which('colmap') is not None and (grut/'train.py').is_file() and shutil.which('nvidia-smi') is not None
    def terminate(process,force=False):
        if process and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):os.killpg(process.pid,signal.SIGKILL if force else signal.SIGTERM)
    async def halt(process):
        terminate(process)
        try:await asyncio.wait_for(asyncio.shield(process.wait()),3)
        except asyncio.TimeoutError:terminate(process,True);await process.wait()
    async def heartbeat():
        while True:
            if any(not j['task'].done() for j in jobs.values()):touch('nurec')
            await asyncio.sleep(10)
    async def pipeline(key,folder):
        state=jobs[key]
        try:
            async with semaphore:
                if state['cancel']:return status(folder,status='cancelled')
                output=folder/'training';colmap=folder/'colmap';(colmap/'sparse').mkdir(parents=True)
                shutil.copytree(folder/'images',colmap/'images')
                commands=[('Matching camera features',['colmap','feature_extractor','--database_path',str(colmap/'database.db'),'--image_path',str(colmap/'images'),'--ImageReader.single_camera','1','--ImageReader.camera_model','PINHOLE']),
                    ('Matching photographs',['colmap','exhaustive_matcher','--database_path',str(colmap/'database.db')]),
                    ('Reconstructing camera positions',['colmap','mapper','--database_path',str(colmap/'database.db'),'--image_path',str(colmap/'images'),'--output_path',str(colmap/'sparse')]),
                    ('Training and exporting NuRec scene',[sys.executable,str(grut/'train.py'),'--config-name','apps/colmap_3dgut_mcmc.yaml',f'path={colmap}',f'out_dir={output}','experiment_name=room','export_usdz.enabled=true','export_usdz.apply_normalizing_transform=false'])]
                for stage,args in commands:
                    if state['cancel']:return status(folder,status='cancelled')
                    status(folder,status='reconstructing',stage=stage)
                    with (folder/'worker.log').open('ab') as log:
                        process=await asyncio.create_subprocess_exec(*args,cwd=grut,stdout=log,stderr=log,start_new_session=True)
                        state['process']=process
                        try:code=await asyncio.wait_for(process.wait(),8*3600)
                        except asyncio.TimeoutError:
                            terminate(process,True);await process.wait();raise ValueError('Reconstruction exceeded the 8 hour stage limit.')
                    if state['cancel']:return status(folder,status='cancelled')
                    if code:raise ValueError(f'{stage} failed (exit {code}). Inspect worker.log on the GPU worker.')
                files=list(output.rglob('export_last.usdz'))
                if len(files)!=1:raise ValueError('3DGUT did not produce one export_last.usdz file.')
                artifact=folder/'scene.usdz';shutil.copyfile(files[0],artifact)
                status(folder,status='ready',stage='Ready for alignment',sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),bytes=artifact.stat().st_size)
        except Exception as error:status(folder,status='failed',error=str(error))
        finally:state['process']=None
    @app.get('/v1/health')
    async def health():return {'protocol':'robot-ide.nurec.v1','engine':'colmap_3dgrut','ready':ready(),'requires':'CUDA GPU, COLMAP, installed 3dgrut environment','metric_scale':'must_be_calibrated','idle_guard_active':guard_status(),'active_jobs':sum(not j['task'].done() for j in jobs.values())}
    @app.post('/v1/jobs',status_code=202)
    async def submit(request:Request):
        if not ready():raise HTTPException(422,'Install COLMAP and 3dgrut in the CUDA worker environment first.')
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>MAX_UPLOAD:raise HTTPException(413,'Capture archive exceeds 512 MB')
        try:
            archive=zipfile.ZipFile(io.BytesIO(body));entries=archive.infolist()
            if not 12<=len(entries)<=500 or sum(i.file_size for i in entries)>MAX_UPLOAD:raise ValueError('Use 12–500 photographs, no more than 512 MB unpacked.')
            if len({i.filename for i in entries})!=len(entries):raise ValueError('Photograph names must be unique.')
            if any('/' in i.filename or '\\' in i.filename or Path(i.filename).suffix.lower() not in {'.jpg','.jpeg','.png'} or i.file_size>12*1024*1024 for i in entries):raise ValueError('Capture archive may contain only flat JPG/PNG photographs up to 12 MB each.')
            key=uuid.uuid4().hex;folder=root/key;(folder/'images').mkdir(parents=True)
            for entry in entries:(folder/'images'/entry.filename).write_bytes(archive.read(entry))
        except (ValueError,zipfile.BadZipFile,RuntimeError) as error:raise HTTPException(422,str(error)) from error
        touch('nurec')
        result=status(folder,id=key,status='queued',stage='Waiting for the GPU',photos=len(entries),error=None)
        jobs[key]={'cancel':False,'process':None};jobs[key]['task']=asyncio.create_task(pipeline(key,folder))
        return result
    @app.get('/v1/jobs/{key}')
    async def read(key:str):return json.loads((directory(key)/'job.json').read_text())
    @app.delete('/v1/jobs/{key}')
    async def cancel(key:str):
        folder=directory(key)
        if key in jobs:
            state=jobs[key];state['cancel']=True
            if state.get('process') and state['process'].returncode is None:await halt(state['process'])
        return status(folder,status='cancelled',stage='Cancelled')
    @app.get('/v1/jobs/{key}/artifact')
    async def artifact(key:str):
        folder=directory(key)
        if json.loads((folder/'job.json').read_text())['status']!='ready':raise HTTPException(409,'Reconstruction is not ready')
        return FileResponse(folder/'scene.usdz',media_type='model/vnd.usdz+zip',filename='scene.usdz')
    return app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(create_worker(),host=os.getenv('NUREC_BIND','127.0.0.1'),port=int(os.getenv('NUREC_PORT','9200')))

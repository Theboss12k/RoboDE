"""Linux-only motion service. Each job owns its own MoveIt planning scene."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import tempfile
from fastapi import FastAPI, HTTPException, Request
from shared.models.robotics import ValidationReport,ValidationFinding
app=FastAPI(title='RoboDE Linux robotics worker',version='2.0')
os.environ.setdefault('ROS_LOG_DIR','/tmp/ros-log')
os.environ.setdefault('ROS_HOME','/tmp/ros-home')
lock=asyncio.Semaphore(1)
@app.middleware('http')
async def authorize(request:Request,call_next):
    from starlette.responses import JSONResponse
    token=os.environ.get('ROBOT_DE_MOTION_TOKEN','')
    if not token or not secrets.compare_digest(request.headers.get('authorization',''),'Bearer '+token):
        return JSONResponse({'detail':'Motion worker token required'},401)
    if int(request.headers.get('content-length','0'))>128*1024*1024:return JSONResponse({'detail':'Job too large'},413)
    return await call_next(request)
@app.get('/v2/health')
async def health():
    available=sys.platform=='linux' and importlib.util.find_spec('moveit') is not None
    return {'available':available,'moveit':available,'nav2':importlib.util.find_spec('nav2_simple_commander') is not None,'revision':'robotics-v2','hardware_validated':False,'message':'Linux MoveIt worker ready' if available else 'MoveIt 2 is unavailable; use the robotics Docker image'}
async def job(operation,body):
    if not (await health())['available']:raise HTTPException(503,'Linux MoveIt 2 runtime is required')
    async with lock:
        with tempfile.TemporaryDirectory(prefix='robode-motion-') as folder:
            source=Path(folder)/'request.json';output=Path(folder)/'result.json';log=Path(folder)/'worker.log'
            source.write_text(json.dumps({'operation':operation,'body':body},allow_nan=False))
            with log.open('wb') as stream:
                process=await asyncio.create_subprocess_exec(sys.executable,'-m','workers.robotics.native',str(source),str(output),stdout=stream,stderr=stream,start_new_session=True)
                try:await asyncio.wait_for(process.wait(),105)
                except BaseException:
                    raise HTTPException(503,'Motion job timed out or was cancelled; no movement was issued')
                finally:
                    # Nav2 lifecycle nodes inherit this job group. Always reap them,
                    # including when the planning parent exits before its children.
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    await process.wait()
            if process.returncode or not output.exists():raise HTTPException(503,'MoveIt job failed. Check the local robotics worker logs; no motion was issued')
            result=json.loads(output.read_text())
            if 'error' in result:raise HTTPException(422,result['error'])
            return result
@app.post('/v2/plan')
async def plan(body:dict):return await job('plan',body)
@app.post('/v2/validate')
async def validate(body:dict):
    try:return await job('validate',body)
    except HTTPException as error:
        return ValidationReport(status='incomplete',findings=[ValidationFinding(code='NATIVE_COVERAGE',message=str(error.detail))])

from workers.robotics.physical import PhysicalRuntime
physical=PhysicalRuntime()
def checked(fn):
    async def invoke(*args):
        try:return await fn(*args)
        except (ValueError,KeyError) as error:raise HTTPException(422,str(error)) from error
    return invoke
@app.post('/v2/physical/connect')
async def connect_physical(body:dict):return await checked(physical.connect)(body)
@app.post('/v2/physical/{cid}/heartbeat')
async def heartbeat_physical(cid:str):return await checked(physical.heartbeat)(cid)
@app.post('/v2/physical/{cid}/arm')
async def arm_physical(cid:str,body:dict):return await checked(physical.arm)(cid,body)
@app.post('/v2/physical/{cid}/execute')
async def execute_physical(cid:str,body:dict):return await checked(physical.execute)(cid,body['authorization'])
@app.post('/v2/physical/{cid}/stop')
async def stop_physical(cid:str):return await checked(physical.stop)(cid)
@app.post('/v2/physical/{cid}/disconnect')
async def disconnect_physical(cid:str):await checked(physical.close)(cid);return {'disconnected':True,'armed':False}
@app.get('/v2/physical/runs/{rid}')
async def physical_run(rid:str):
    if rid not in physical.runs:raise HTTPException(404,'Physical run not found')
    return physical.public(physical.runs[rid])

@app.post('/v2/physical/execute-group')
async def execute_group(body:dict):
    import time
    selected=body['tokens']
    if not selected or len(selected)>16 or len({t['connection_id'] for t in selected})!=len(selected):raise HTTPException(422,'Select distinct connected devices')
    for item in selected:
        a=physical.authorizations.get(item['authorization'])
        if not a or a['connection']!=item['connection_id'] or a['expires']<time.monotonic():raise HTTPException(422,'One device authorization expired; no device was started')
        c=physical.connection(item['connection_id']);await physical.heartbeat(item['connection_id']);physical.batches(a['body'],c)
    physical.group_start=time.monotonic()+.5
    try:
        return {'runs':[await physical.execute(t['connection_id'],t['authorization']) for t in selected]}
    except BaseException:
        await asyncio.gather(*(physical.stop(t['connection_id']) for t in selected),return_exceptions=True);raise
    finally:physical.group_start=None

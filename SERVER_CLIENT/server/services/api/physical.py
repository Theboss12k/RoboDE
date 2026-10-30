"""IDE-only approval of immutable revisions; Business can request and Stop."""
import asyncio
from datetime import datetime,timezone
import json
import math
import os
import uuid
from fastapi import APIRouter,HTTPException
from services.api.storage import atomic_json,fingerprint,safe_id
from services.validation.registry import validate_positions
from shared.models.domain import Run,Lifecycle,Log,now


def physical_router(store,controller,controls):
    router=APIRouter(prefix='/api');connections={};authorizations={}
    controller.physical_connections=connections
    def path(pid,rid):return store.runtime/'physical_approvals'/safe_id(pid)/(safe_id(rid)+'.json')
    async def remaining():
        if controller.gpu.enabled():
            vm=await controller.gpu.describe(controller.gpu.configuration())
            if vm.get('status')!='RUNNING' or not vm.get('lastStartTimestamp'):raise ValueError('Cannot establish remaining cloud runtime')
            start=datetime.fromisoformat(vm['lastStartTimestamp'].replace('Z','+00:00'))
            return max(0,7200-(datetime.now(timezone.utc)-start).total_seconds())
        if os.getenv('ROBOT_IDE_DEPLOYMENT')=='cloud':
            deadline=os.getenv('ROBOT_DE_CLOUD_DEADLINE')
            if not deadline:raise ValueError('Cloud physical execution requires a trusted shutdown deadline from the VM supervisor')
            return max(0,(datetime.fromisoformat(deadline.replace('Z','+00:00'))-datetime.now(timezone.utc)).total_seconds())
        return 7200.
    def request_record(pid,planid):
        p=path(pid,planid)
        return json.loads(p.read_text()) if p.exists() else {'project_id':pid,'revision_id':planid,'status':'not_requested'}
    def revision(pid,planid):
        p=store.get_plan(pid,planid)
        if not p.validation_report or p.validation_report.status!='passed':raise ValueError('Physical execution requires a complete passed physical-check report; Incomplete blocks movement')
        if not p.valid or not p.motion_manifest or not p.definition_id:raise ValueError('Compile this plan with the typed command dispatcher before physical execution')
        if store.get_definition(pid,p.definition_id).version!=p.definition_version:raise ValueError('Physical revision is stale; validate again')
        return p
    @router.get('/projects/{pid}/plans/{planid}/physical-approval')
    async def approval(pid:str,planid:str):store.get_plan(pid,planid);return request_record(pid,planid)
    @router.get('/physical/requests')
    async def requests():return [json.loads(p.read_text()) for p in sorted((store.runtime/'physical_approvals').glob('*/*.json'))]
    @router.post('/projects/{pid}/robots/{rid}/physical-connect')
    async def connect(pid:str,rid:str,body:dict):
        controller.ensure_idle(pid)
        if controls.sessions:raise ValueError('Close manual controls before connecting physical execution')
        *_,cell,_=await controller.context(pid,rid);model=cell.models[rid];binding=model.get('binding')
        if not binding or not binding['published']:raise ValueError('Select a published robot-driver binding first')
        if cell.remote:raise ValueError('Use built-in preview for measured physical starting-state synchronization')
        driver=controller.drivers.get(binding['definition']['driver_id'])
        pending_owner='physical-connect:'+uuid.uuid4().hex
        controller.resources.acquire(['device:'+body['device_id']],pending_owner)
        try:result=await controller.motion.request('/v2/physical/connect',{'project_id':pid,'device_id':body['device_id'],'bundle':driver,'binding_hash':binding['hash'],'connection':body.get('connection',{}),'warning_acknowledgement':body.get('warning_acknowledgement')})
        except BaseException:
            controller.resources.release(pending_owner);raise
        cid=result['connection_id'];q=dict((await controller.states(cell))[rid].positions)
        try:
            for j in binding['definition']['joints']:
                if j['role']=='independent':
                    f=next(f for f in driver['definition']['functions'] if f['id']==j['function_id'])
                    if f['mode']=='position':q[j['joint_id']]=(result['feedback']['positions'][j['function_id']]-j['offset'])/j['scale']
            if model.get('mobility',{}).get('classification','STATIONARY')!='STATIONARY':
                base=result['feedback'].get('base_pose')
                if not base or any(not isinstance(base.get(k),(int,float)) or not math.isfinite(base[k]) for k in ('x','y','yaw')):raise ValueError('Mobile physical connections require measured odometry in the configured world frame')
                cell.base_poses[rid]={**model.get('base_pose',{}),**base};cell.models[rid]['base_pose']=cell.base_poses[rid]
            validate_positions(model,q);await cell.adapters[rid].command(q);await cell.adapters[rid].request_stop()
            await controller.persist_state(pid)
            controller.resources.release(pending_owner);controller.resources.acquire(['device:'+body['device_id']],cid)
            connections[cid]={'project_id':pid,'robot_id':rid,'device_id':body['device_id'],'binding_hash':binding['hash'],'binding':binding,'feedback':result['feedback']}
        except BaseException:
            controller.resources.release(pending_owner);controller.resources.release(cid)
            await controller.motion.request('/v2/physical/'+cid+'/disconnect',{});raise
        return {**result,'robot_id':rid,'requires_recompile':True,'message':'Measured joint state synchronized to the built-in preview. Validate a new revision before arming.'}
    @router.post('/physical/connections/{cid}/heartbeat')
    async def heartbeat(cid:str):
        if cid not in connections:raise ValueError('Reconnect the physical device')
        try:
            feedback=await controller.motion.request('/v2/physical/'+safe_id(cid)+'/heartbeat',{});connections[cid]['feedback']=feedback;return feedback
        except BaseException:
            connections.pop(cid,None);controller.resources.release(cid);raise
    @router.post('/physical/connections/{cid}/disconnect')
    async def disconnect(cid:str):
        try:return await controller.motion.request('/v2/physical/'+safe_id(cid)+'/disconnect',{})
        finally:connections.pop(cid,None);controller.resources.release(cid)
    @router.post('/projects/{pid}/plans/{planid}/arm-physical')
    async def arm(pid:str,planid:str,body:dict):
        controller.ensure_idle(pid);plan=revision(pid,planid)
        if body.get('operator_acknowledgement')!='Arm this exact physical revision':raise ValueError('Explicit IDE operator arming is required')
        if fingerprint(await controller.snapshot(pid))!=plan.fingerprint:raise ValueError('Scene or starting configuration changed; validate again')
        ids=body['connections'];required={t.robot_id for t in plan.atomic_tasks if t.robot_id};selected={connections[cid]['robot_id']:cid for cid in ids if cid in connections and connections[cid]['project_id']==pid}
        if set(selected)!=required:raise ValueError('Connect every robot assigned by the physical revision')
        *_,cell,_=await controller.context(pid)
        budget=await remaining();tokens=[]
        try:
            for rid,cid in selected.items():
                c=connections[cid]
                if c['binding_hash']!=controller.bindings.get(c['binding']['id'])['hash']:raise ValueError('Robot mapping changed; reconnect and validate again')
                from services.commands.standard import tool_component
                checks=[];model=cell.models[rid]
                for task in plan.motion_manifest['tasks']:
                    if task.get('robot_id')!=rid:continue
                    for goal in task['normalized']:
                        if goal['kind'] not in {'grasp','release','verify'}:continue
                        check={**goal,'time':plan.task_schedule[task['id']]['end'],'task_id':task['id']}
                        if goal['kind']=='verify':
                            check['target']=next(o.model_dump(mode='json') for o in cell.objects if o.id==goal['target_id'])
                            check['object']=next(o.model_dump(mode='json') for o in cell.objects if o.id==goal['object_id'])
                        if goal['kind']=='release':
                            component=tool_component(model,goal['end_effector'])
                            mapping=next(j for j in c['binding']['definition']['joints'] if j['joint_id']==component['actuator'])
                            check.update(gripper_function=mapping['function_id'],gripper_open=component['open']*mapping['scale']+mapping['offset'])
                        checks.append(check)
                b={'postconditions':checks,'revision_id':planid,'frames':[{'time':f.time,'positions':f.robot_positions[rid],'base_pose':f.base_poses.get(rid),'held_object':f.held_objects.get(rid),'grasp_verifying':rid in f.pending_grasps} for f in plan.frames],
                    'binding':c['binding'],'validation':plan.validation_report.model_dump(mode='json'),'remaining_seconds':budget,
                    'purpose':body.get('purpose','plan'),'operator_acknowledgement':body['operator_acknowledgement'],'hardware_motion_reviewed':body.get('hardware_motion_reviewed',False)}
                result=await controller.motion.request('/v2/physical/'+cid+'/arm',b);tokens.append({'connection_id':cid,'authorization':result['authorization']})
            token=uuid.uuid4().hex;authorizations[token]={'project_id':pid,'plan_id':planid,'connections':ids,'tokens':tokens,'expires':asyncio.get_running_loop().time()+30,'fingerprint':plan.fingerprint}
            record={'project_id':pid,'revision_id':planid,'status':'armed','armed_at':now(),'expires_in':30,'devices':[connections[c]['device_id'] for c in ids]};atomic_json(path(pid,planid),record)
            return {'authorization':token,**record}
        except BaseException:
            await asyncio.gather(*(controller.motion.request('/v2/physical/'+t['connection_id']+'/stop',{}) for t in tokens),return_exceptions=True);raise
    @router.post('/projects/{pid}/plans/{planid}/execute-physical',status_code=202)
    async def execute(pid:str,planid:str,body:dict):
        controller.ensure_idle(pid);plan=revision(pid,planid);a=authorizations.pop(body['authorization'],None)
        if not a or a['project_id']!=pid or a['plan_id']!=planid or a['expires']<asyncio.get_running_loop().time():raise ValueError('Authorization expired; review and arm the exact revision again')
        if fingerprint(await controller.snapshot(pid))!=a['fingerprint']:raise ValueError('Environment changed after arming')
        if plan.duration+60>await remaining():raise ValueError('Insufficient cloud runtime for movement and stopping')
        run=Run(id=uuid.uuid4().hex[:12],project_id=pid,plan_id=planid,revision_id=planid,definition_id=plan.definition_id,mode='physical',adapter='physical',status=Lifecycle.EXECUTING)
        controller.resources.acquire(['environment:'+pid],run.id);controller.leases[pid]=run.id;controller.runs[run.id]=run;store.save_run(run)
        async def monitor():
            try:
                result=await controller.motion.request('/v2/physical/execute-group',{'tokens':a['tokens']});remote=result['runs']
                while True:
                    if run.stop_requested:await asyncio.gather(*(controller.motion.request('/v2/physical/'+c+'/stop',{}) for c in a['connections']))
                    states=await asyncio.gather(*(controller.motion.request('/v2/physical/runs/'+r['id']) for r in remote))
                    run.progress=min(r['progress'] for r in states);run.elapsed=plan.duration*run.progress
                    from shared.models.domain import RobotState
                    observed={}
                    for cid,remote_state in zip(a['connections'],states):
                        c=connections[cid]
                        if remote_state.get('feedback'):c['feedback']=remote_state['feedback']
                        feedback=c['feedback'];q={j['joint_id']:(feedback['positions'][j['function_id']]-j['offset'])/j['scale'] for j in c['binding']['definition']['joints'] if j['role']=='independent'}
                        q={**plan.frames[0].robot_positions[c['robot_id']],**q}
                        observed[c['robot_id']]=RobotState(instance_id=c['robot_id'],positions=q,source='hardware',measured_at=feedback['measured_at'],stopped=feedback['stopped'],base_pose=feedback.get('base_pose'))
                    run.robot_states=observed
                    measured_objects=dict(plan.frames[0].objects)
                    from shared.models.domain import Pose
                    for cid in a['connections']:
                        for oid,p in connections[cid]['feedback'].get('objects',{}).items():measured_objects[oid]=Pose.model_validate(p)
                    run.evidence['scene_feedback']='Configured scene positions are retained unless the SDK supplies measured object poses'
                    predicted=min(plan.frames,key=lambda f:abs(f.time-run.elapsed));run.frame=predicted.model_copy(update={'robot_positions':{**predicted.robot_positions,**{rid:s.positions for rid,s in observed.items()}},'positions':observed.get(plan.task.robot_id,next(iter(observed.values()))).positions,'objects':measured_objects})
                    run.current_step=run.frame.step_id
                    run.step_statuses={task.id:'done' if run.elapsed>=plan.task_schedule[task.id]['end'] else 'running' if run.elapsed>=plan.task_schedule[task.id]['start'] else 'pending' for task in plan.atomic_tasks}
                    store.save_run(run)
                    if any(r['status']=='failed' for r in states):raise ValueError('; '.join(r.get('error') or '' for r in states if r['status']=='failed'))
                    if all(r['status']!='running' for r in states):
                        run.stopped_verified=all(r['stopped_verified'] for r in states);run.status=Lifecycle.CANCELLED if run.stop_requested else Lifecycle.COMPLETED
                        if not run.stopped_verified:raise ValueError('Stopped feedback was not confirmed for every device')
                        break
                    await asyncio.sleep(.1)
            except BaseException as error:
                run.status=Lifecycle.FAILED;run.logs.append(Log(level='error',message=str(error)))
                await asyncio.gather(*(controller.motion.request('/v2/physical/'+c+'/stop',{}) for c in a['connections']),return_exceptions=True)
            finally:
                run.finished_at=now();store.save_run(run);controller.leases.pop(pid,None);controller.resources.release(run.id)
                record=request_record(pid,planid);record.update(status=run.status.value.lower(),run_id=run.id);atomic_json(path(pid,planid),record)
        record=request_record(pid,planid);record.update(status='executing',run_id=run.id);atomic_json(path(pid,planid),record)
        controller.jobs[run.id]=asyncio.create_task(monitor());return run
    return router

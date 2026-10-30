"""Onsite physical execution with consumed authorization and device ownership.

The API process never executes generated plan Python. This service dispatches
prevalidated, bounded joint batches to a supervised driver subprocess. The
subprocess owns a second watchdog, and a documented device watchdog is required.
"""
import asyncio
import hashlib
import math
import secrets
import time
from datetime import datetime,timezone
from services.adapters.drivers import DriverProcess,driver_hash
from services.api.storage import fingerprint


class PhysicalRuntime:
    def __init__(self):self.connections={};self.devices={};self.authorizations={};self.runs={};self.watchdog=None
    def require_feedback(self,state,device_id):
        if state.get('source')!='hardware' or state.get('device_id')!=device_id or not state.get('connected'):raise ValueError('Measured feedback must identify the connected device')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['measured_at'].replace('Z','+00:00'))).total_seconds()
        if not -.1<=age<=1.:raise ValueError('Hardware feedback is stale')
        if state.get('stopped') and any(abs(v)>1e-3 for v in state.get('velocities',{}).values()):raise ValueError('Stopped feedback contradicts measured velocity')
        if not isinstance(state.get('stopped'),bool):raise ValueError('Hardware must report confirmed stopped feedback separately from Stop requests')
        return state
    async def connect(self,body):
        if body.get('warning_acknowledgement')!='I understand this connects to physical hardware':raise ValueError('Acknowledge the red physical-connection warning first')
        b=body['bundle'];device=body['device_id']
        if b['hash']!=driver_hash(b) or b.get('reviewed_hash')!=b['hash'] or not (b.get('test_report') or {}).get('passed'):raise ValueError('Exact reviewed and simulated-tested driver required')
        if b['definition']['category']!='physical':raise ValueError('Choose a physical driver')
        if not b['definition'].get('watchdog_method'):raise ValueError('Document and configure the device communication-loss watchdog before live connection')
        if device in self.devices:raise ValueError('This device is owned by another project or control session')
        token=secrets.token_hex(24);self.devices[device]=token;process=DriverProcess()
        try:
            state=await process.start(b,mode='live',connection=body.get('connection',{}))
            self.require_feedback(state,device)
            await process.request({'operation':'stop'});state=self.require_feedback(await process.request({'operation':'state'}),device)
            if not state['stopped']:raise ValueError('The device has not confirmed stopped feedback')
            self.connections[token]={'process':process,'device_id':device,'bundle':b,'state':state,'touched':time.monotonic(),'driver_hash':b['hash'],'binding_hash':body['binding_hash'],'project_id':body['project_id'],'qualified_functions':set()}
            if not self.watchdog or self.watchdog.done():self.watchdog=asyncio.create_task(self.monitor())
            return {'connection_id':token,'feedback':state,'qualification':{'feedback_and_stop_validated':True,'motion_validated':False},'armed':False}
        except BaseException:self.devices.pop(device,None);await process.close();raise
    def connection(self,cid):
        c=self.connections.get(cid)
        if not c:raise ValueError('Physical connection expired; reconnect and review authorization')
        return c
    async def heartbeat(self,cid):
        c=self.connection(cid);state=self.require_feedback(await c['process'].request({'operation':'heartbeat'}),c['device_id']);c.update(touched=time.monotonic(),state=state);return state
    def batches(self,body,c):
        mapping=body['binding']['definition']['joints'];driver=c['bundle']['definition'];functions={f['id']:f for f in driver['functions']};frames=body['frames'];result=[]
        if len(frames)<2 or len(frames)>216000:raise ValueError('A bounded trajectory is required')
        if body['binding']['hash']!=c['binding_hash'] or body['binding']['driver_hash']!=c['driver_hash']:raise ValueError('Physical binding or driver changed')
        previous=-1.
        for i,frame in enumerate(frames):
            t=frame['time'];q=frame['positions']
            if not isinstance(t,(int,float)) or isinstance(t,bool) or not math.isfinite(t):raise ValueError('Trajectory time must be finite')
            if not 0<=t<=7140:raise ValueError('Physical trajectory exceeds the two-hour window and stopping allowance')
            if i and t-previous>.101:raise ValueError('Physical control samples must provide continuous bounded feedback updates')
            if not isinstance(t,(int,float)) or isinstance(t,bool) or not math.isfinite(t) or t<=previous or (i==0 and t!=0):raise ValueError('Trajectory times must increase from zero')
            if set(q)!={j['joint_id'] for j in mapping}:raise ValueError('Every physical frame must include all configured joints')
            batch=[]
            for joint in mapping:
                if joint['role']!='independent':continue
                f=functions[joint['function_id']];v=q[joint['joint_id']]
                if f['mode']=='velocity':
                    if i==0 or i==len(frames)-1:v=0.
                    else:v=(q[joint['joint_id']]-frames[i-1]['positions'][joint['joint_id']])/(t-frames[i-1]['time'])
                    value=v*joint['scale']
                else:value=v*joint['scale']+joint['offset']
                if isinstance(value,bool) or not math.isfinite(value) or not f['minimum']<=value<=f['maximum']:raise ValueError('Physical command exceeds the driver limits')
                batch.append({'function':f['id'],'value':value})
            result.append({'time':t,'commands':batch,'positions':q});previous=t
        # Validate the entire trajectory before any movement is issued.
        start=c['state']['positions']
        for joint in mapping:
            if joint['role']!='independent':continue
            f=functions[joint['function_id']]
            if f['mode']=='position' and abs(start[f['id']]-(frames[0]['positions'][joint['joint_id']]*joint['scale']+joint['offset']))>body.get('start_tolerance',.001):raise ValueError('Measured starting state differs from this revision')
        mobility=body['binding']['definition'].get('mobility',{})
        if mobility.get('classification','STATIONARY')!='STATIONARY':
            measured=c['state'].get('base_pose');expected=frames[0].get('base_pose')
            if not measured or not expected:raise ValueError('Mobile physical runs require measured odometry and a compiled starting base pose')
            if any(not isinstance(measured.get(k),(int,float)) or not math.isfinite(measured[k]) for k in ('x','y','yaw')):raise ValueError('Mobile odometry must contain finite x, y and yaw')
            yaw_error=abs(math.atan2(math.sin(measured['yaw']-expected['yaw']),math.cos(measured['yaw']-expected['yaw'])))
            if math.hypot(measured['x']-expected['x'],measured['y']-expected['y'])>.005 or yaw_error>.01:raise ValueError('Measured starting base pose differs from this revision')
        return result
    async def arm(self,cid,body):
        c=self.connection(cid);await self.heartbeat(cid)
        if not c['state']['stopped']:raise ValueError('Confirmed stopped feedback is required before arming')
        if body.get('validation',{}).get('status')!='passed' or body['validation'].get('hardware_validated'):raise ValueError('A complete physical-check report is required; simulation readiness cannot be substituted')
        if not body.get('hardware_motion_reviewed'):raise ValueError('Operator review of this device and mapping is required')
        if body.get('operator_acknowledgement')!='Arm this exact physical revision':raise ValueError('Explicit physical execution arming is required')
        if body['frames'][-1]['time']+60>body['remaining_seconds']:raise ValueError('Motion and stopping allowance exceed the remaining cloud session')
        batches=self.batches(body,c)
        required={j['function_id'] for j in body['binding']['definition']['joints'] if j['role']=='independent'}
        if body.get('purpose')=='actuator_qualification':
            changed={f['id'] for f in c['bundle']['definition']['functions'] if any(abs(next(x['value'] for x in batch['commands'] if x['function']==f['id'])-next(x['value'] for x in batches[0]['commands'] if x['function']==f['id']))>1e-8 for batch in batches[1:])}
            if len(changed)!=1:raise ValueError('Hardware qualification must exercise exactly one actuator')
            function=next(f for f in c['bundle']['definition']['functions'] if f['id'] in changed);limit={'m':.005,'mm':5.,'deg':1.,'rad':.02,'rad/s':.05,'deg/s':2.}.get(function.get('unit','rad'),.005)
            values=[next(x['value'] for x in batch['commands'] if x['function']==function['id']) for batch in batches]
            if max(values)-min(values)>limit:raise ValueError('Qualification motion exceeds the bounded single-actuator test range')
            body={**body,'qualification_function':function['id']}
        elif not required.issubset(c.get('qualified_functions',set())):raise ValueError('Run hardware qualification for every independent actuator on this exact device and binding before a physical plan')
        digest=fingerprint({k:body[k] for k in ('revision_id','frames','binding','validation')})
        token=secrets.token_urlsafe(24);self.authorizations[token]={'connection':cid,'digest':digest,'expires':time.monotonic()+30,'body':body,'batches':batches};return {'authorization':token,'expires_in':30,'revision_id':body['revision_id'],'device_id':c['device_id'],'digest':digest}
    async def execute(self,cid,token):
        authorization=self.authorizations.pop(token,None)
        if not authorization or authorization['connection']!=cid or authorization['expires']<time.monotonic():raise ValueError('Physical authorization expired or was already consumed')
        c=self.connection(cid)
        if not getattr(self,'group_start',None):await self.heartbeat(cid)
        if any(r['connection']==cid and r['status']=='running' for r in self.runs.values()):raise ValueError('Physical device is already executing')
        batches=self.batches(authorization['body'],c);rid=secrets.token_hex(8)
        run={'id':rid,'connection':cid,'revision_id':authorization['body']['revision_id'],'status':'running','stop_requested':False,'stopped_verified':False,'progress':0.,'error':None};self.runs[rid]=run
        run['start_time']=getattr(self,'group_start',None);run['job']=asyncio.create_task(self.run(run,c,batches,authorization['body']));return self.public(run)
    def public(self,run):return {k:v for k,v in run.items() if k not in {'job','connection'}}
    def verify_postcondition(self,check,state):
        kind=check['kind'];oid=check['object_id']
        if kind in {'grasp','release'}:
            if state.get('attachment_source')!='hardware_sensor' or 'attachments' not in state:raise ValueError('Task result requires measured hardware attachment feedback')
            attached=oid in state['attachments']
            if attached!=(kind=='grasp'):raise ValueError('Measured attachment does not satisfy task '+check['task_id'])
            if kind=='release' and abs(state['positions'][check['gripper_function']]-check['gripper_open'])>.002:raise ValueError('Gripper has not confirmed release opening')
        elif kind=='verify':
            from shared.models.domain import WorldObject,Pose
            from services.world_model.world import placement_satisfied
            position=state.get('objects',{}).get(oid)
            if position is None:raise ValueError('Placement verification requires a measured object pose from the hardware sensor')
            item=WorldObject.model_validate(check['object']).model_copy(update={'position':Pose.model_validate(position)})
            if not placement_satisfied(item,WorldObject.model_validate(check['target']),check.get('placement','inside')):raise ValueError('Measured object placement does not satisfy task '+check['task_id'])
            if state.get('attachment_source')!='hardware_sensor' or oid in state.get('attachments',[oid]):raise ValueError('Placement verification requires confirmed object detachment')

    async def run(self,run,c,batches,body):
        started=run.get('start_time') or time.monotonic();verified=set()
        try:
            for frame in batches:
                if run['stop_requested']:break
                delay=started+frame['time']-time.monotonic()
                if delay>0:await asyncio.sleep(delay)
                if run['stop_requested']:break
                if time.monotonic()-(started+frame['time'])>.15:raise ValueError('SDK missed the approved command timing; refusing to replay a delayed movement backlog')
                if time.monotonic()-c['touched']>3:raise ValueError('IDE connection lost; physical motion cancelled')
                state=self.require_feedback(await c['process'].request({'operation':'command','commands':frame['commands']}),c['device_id'])
                c['state']=state;run['feedback']=state
                expected_object=next((f.get('held_object') for f in reversed(body['frames']) if f['time']<=frame['time']+1e-9),None)
                verifying=next((f.get('grasp_verifying',False) for f in reversed(body['frames']) if f['time']<=frame['time']+1e-9),False)
                if expected_object and not verifying and (state.get('attachment_source')!='hardware_sensor' or expected_object not in state.get('attachments',[])):raise ValueError('Grasp is not confirmed by measured attachment feedback; closing the gripper alone is insufficient')
                if body['binding']['definition'].get('mobility',{}).get('classification','STATIONARY')!='STATIONARY':
                    expected=next(f.get('base_pose') for f in body['frames'] if f['time']==frame['time']);actual=state.get('base_pose')
                    if not actual or math.hypot(actual['x']-expected['x'],actual['y']-expected['y'])>.03 or abs(actual['yaw']-expected['yaw'])>.08:raise ValueError('Measured base odometry does not track the approved navigation path')
                for j in body['binding']['definition']['joints']:
                    if j['role']!='independent':continue
                    function=next(f for f in c['bundle']['definition']['functions'] if f['id']==j['function_id'])
                    error=(state['positions'][function['id']]-j['offset'])/j['scale']-frame['positions'][j['joint_id']]
                    if j['joint_id'] in [body['binding']['definition'].get('mobility',{}).get(w) for w in ('left_wheel','right_wheel')]:error=math.atan2(math.sin(error),math.cos(error))
                    tolerance=.002 if function.get('unit','rad').removesuffix('/s') in {'m','mm'} else .02
                    if abs(error)>tolerance:raise ValueError('Measured actuator position does not track the approved motion')
                for command in frame['commands']:
                    f=next(f for f in c['bundle']['definition']['functions'] if f['id']==command['function'])
                    if f['mode']=='velocity' and abs(state['velocities'][f['id']]-command['value'])>body.get('velocity_tracking_tolerance',.1):raise ValueError('Measured actuator velocity does not track the approved command')
                    if f['mode']=='position' and abs(state['positions'][f['id']]-command['value'])>body.get('tracking_tolerance',.02):raise ValueError('Measured hardware tracking exceeds approved tolerance')
                for index,check in enumerate(body.get('postconditions',[])):
                    if index not in verified and frame['time']+1e-6>=check['time']:
                        self.verify_postcondition(check,state);verified.add(index)
                run['progress']=frame['time']/batches[-1]['time']
            run['status']='cancelled' if run['stop_requested'] else 'completed'
        except BaseException as error:run['status']='failed';run['error']=str(error)
        finally:
            try:
                await c['process'].request({'operation':'stop'});state=self.require_feedback(await c['process'].request({'operation':'state'}),c['device_id']);run['stopped_verified']=state['stopped'];c['state']=state
                if not state['stopped']:run.update(status='failed',error='Stop requested but stopped feedback is not confirmed')
                elif run['status']=='completed' and body.get('qualification_function'):
                    c.setdefault('qualified_functions',set()).add(body['qualification_function']);run['qualified_functions']=sorted(c['qualified_functions'])
            except Exception as error:run.update(status='failed',error='Stop not confirmed: '+str(error))
    async def stop(self,cid):
        c=self.connection(cid)
        for token,a in list(self.authorizations.items()):
            if a['connection']==cid:self.authorizations.pop(token,None)
        for run in self.runs.values():
            if run['connection']==cid and run['status']=='running':run['stop_requested']=True
        state=await c['process'].request({'operation':'stop'});c['state']=state
        return {'stop_requested':True,'stopped_verified':state.get('stopped') is True,'feedback':state}
    async def close(self,cid):
        c=self.connections.get(cid)
        if not c:return
        try:await self.stop(cid)
        finally:
            await c['process'].close();self.connections.pop(cid,None);self.devices.pop(c['device_id'],None)
    async def monitor(self):
        while self.connections:
            for cid,c in list(self.connections.items()):
                if time.monotonic()-c['touched']>3:
                    try:await self.close(cid)
                    except Exception:pass
            await asyncio.sleep(.2)

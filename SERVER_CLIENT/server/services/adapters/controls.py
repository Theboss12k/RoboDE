"""Manual control sessions with explicit target selection and shared ownership."""
import asyncio
import contextlib
import math
import os
import time
import uuid
from datetime import datetime, timezone
from services.adapters.generation import AdapterProcess, GenerateAdapter
from services.adapters.commands import AdapterCommand, compile_recipe
from services.planning.kinematics import with_base, supports_model
from shared.models.domain import now
from services.adapters.profiles import get_profile
from services.execution.resources import environment_resource
from services.validation.registry import validate_positions
from services.validation.trajectory import validate_trajectory
from services.planning.workflow import validate_cell
from shared.models.domain import Frame,RobotState
from services.world_model.world import object_map


class ManualControls:
    def __init__(self,registry,controller):
        self.registry,self.controller = registry,controller
        self.sessions = {}
        self.watchdog = None

    def public(self,s):
        return {k:v for k,v in s.items() if k not in {'process','touched','armed_until','bundle','lock','command_job','command_cancel','library_context'}} | {
            'armed':s['armed_until']>time.monotonic(),'expires_in':max(0,15-(time.monotonic()-s['touched']))}

    def context(self,s):
        if s.get('library_context'):
            instance,model=s['library_context']
            return {},[instance],[model],[]
        return self.registry.store.load_project(s['project_id'])

    async def open_library(self,model_id,adapter_id):
        from services.validation.registry import load_model,load_instance
        folder=self.registry.store.model_folder(model_id);model=load_model(folder)
        instance=load_instance(folder/'instances/instance.yaml',model)
        return await self.open('library:'+model_id,instance['instance']['id'],adapter_id,library_context=(instance,model))

    async def open(self,project_id,robot_id,adapter_id,mode='test',profile_id=None,preview=None,library_context=None):
        if preview and mode!='test':raise ValueError('Draft previews require an isolated simulated transport')
        if library_context:
            if mode!='test' or profile_id or preview:raise ValueError('Global library tests use simulated transport only')
            instances,models=[library_context[0]],[library_context[1]]
        else:
            _,instances,models,_ = self.registry.store.load_project(project_id)
        index = next((n for n,i in enumerate(instances) if i['instance']['id']==robot_id),None)
        if index is None:
            raise ValueError('Unknown project robot instance')
        instance,model = instances[index],models[index]
        if preview:
            validate_positions(model,preview['positions'])
            self.check_base(preview['base_pose'])
        state = RobotState(instance_id=robot_id,positions=instance['initial_configuration']['actuator_positions'],source='simulation')
        environment = None
        if mode == 'environment':
            _,instance,model,environment,state = await self.controller.context(project_id,robot_id)
        if adapter_id in {'mock','isaac_sim'}:
            bundle = await self.registry.generate(GenerateAdapter(model_id=model['robot']['id'],name='Built-in simulator' if adapter_id=='mock' else 'Isaac Sim',kind=adapter_id),state.positions)
            bundle['internal'] = True
            self.registry.save(bundle)
            bundle = self.registry.review(bundle['id'],bundle['hash'])
            bundle = await self.registry.test(bundle['id'])
        else:
            bundle = self.registry.get(adapter_id)
        if preview and (bundle['reviewed_hash']!=bundle['hash'] or not (bundle.get('test_report') or {}).get('passed')):
            raise ValueError('Review and pass adapter tests before using the environment draft editor')
        if bundle['model_id'] != model['robot']['id']:
            raise ValueError('Adapter belongs to a different robot model')
        if mode not in {'test','environment','live'}:
            raise ValueError('Choose test, environment or live controls')
        if mode != 'test' and (bundle['reviewed_hash'] != bundle['hash'] or not (bundle.get('test_report') or {}).get('passed')):
            raise ValueError('Review and pass adapter contract tests before connecting')
        if mode == 'live' and bundle['kind'] != 'ros2':
            raise ValueError('Custom SDK drafts remain test-only until a concrete transport integration is validated')
        if mode == 'environment' and (bundle['category'] != 'virtual' or bundle['kind'] != environment.backend):
            raise ValueError('Select the matching virtual adapter in Environment first')
        connection = bundle['connection']
        if profile_id:
            profile = get_profile(self.registry.store,project_id,robot_id,profile_id)
            if profile['adapter_id'] != bundle['id'] or profile['adapter_hash'] != bundle['hash']:
                raise ValueError('Connection profile references a different or changed adapter')
            connection = profile['connection']
        sid = uuid.uuid4().hex[:20]
        process = AdapterProcess()
        session = {'id':sid,'project_id':project_id,'robot_id':robot_id,'adapter_id':adapter_id,'mode':mode,
                   'category':bundle['category'],'profile_id':profile_id,'feedback':None,'stop_requested':False,'stopped_verified':False,
                   'connection_validated':False,'armed_until':0.,'touched':time.monotonic(),'process':process,'bundle':bundle,'lock':asyncio.Lock(),'command_job':None,'command_cancel':asyncio.Event(),'command_run':None}
        if library_context:session['library_context']=library_context
        if preview:session['preview_base']=preview['base_pose']
        try:
            if mode == 'environment':
                self.controller.resources.acquire([environment_resource(project_id,environment.backend)],sid)
                feedback = state.model_dump(mode='json')
            else:
                token = ''
                if mode == 'live':
                    env_name = connection.get('token_env','ROS_BRIDGE_TOKEN')
                    token = os.getenv(env_name,'')
                    if len(token)<16:
                        raise ValueError('Set the bridge token environment variable (at least 16 characters)')
                feedback = await process.start({**bundle,'connection':connection},'live' if mode=='live' else 'test',token)
                if mode=='test':
                    # A global adapter is reusable; each instance supplies its own
                    # starting pose to the injected transport, never to hardware.
                    feedback=await process.request({'operation':'command','positions':state.positions})
                if preview:
                    feedback=await process.request({'operation':'command','positions':preview['positions']})
                if mode == 'live':
                    self.check_feedback(session,feedback)
                    if not feedback.get('device_id'):
                        raise ValueError('Bridge did not identify its physical device')
                    self.controller.resources.acquire(['device:'+feedback['device_id']],sid)
                else:
                    self.controller.resources.acquire([f'test:{project_id}:{robot_id}:{adapter_id}'],sid)
            session['feedback'] = feedback
            session['stopped_verified'] = feedback['stopped']
            self.sessions[sid] = session
            if not self.watchdog:
                self.watchdog = asyncio.create_task(self.expire())
            return self.public(session)
        except BaseException:
            self.controller.resources.release(sid)
            await process.close()
            raise

    @staticmethod
    def check_base(base):
        if set(base)!={'x','y','z','yaw'} or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in base.values()):
            raise ValueError('Robot placement requires finite X, Y, Z and yaw')

    async def preview_base(self,sid,base):
        s=self.get(sid)
        if s['mode']!='test' or 'preview_base' not in s:
            raise ValueError('Only isolated environment previews can override their base frame')
        self.check_base(base)
        async with s['lock']:
            s['preview_base']=dict(base)
            s['touched']=time.monotonic()
            return self.public(s)

    def get(self,sid):
        if sid not in self.sessions:
            raise ValueError('Control session expired or disconnected; reconnect')
        return self.sessions[sid]

    def check_feedback(self,s,feedback):
        validate_positions({'actuators':{'actuators':s['bundle']['controls']}},feedback['positions'])
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(feedback['measured_at'])).total_seconds()
        if not feedback.get('connected') or not -.5 <= age <= 1.5:
            raise ValueError('Fresh connected robot feedback is required')
        if s['mode']=='live' and feedback.get('source')!='hardware':
            raise ValueError('Live controls require hardware feedback')
        if s['feedback'] and s['mode']=='live' and s['feedback'].get('device_id') != feedback.get('device_id'):
            raise ValueError('Device identity changed; reconnect and validate')

    async def feedback(self,s):
        if s['mode']=='environment':
            *_,state = await self.controller.context(s['project_id'],s['robot_id'])
            return state.model_dump(mode='json')
        return await s['process'].request({'operation':'state'})

    async def read(self,sid):
        s = self.get(sid)
        async with s['lock']:
            try:
                if self.registry.get(s['bundle']['id'])['hash'] != s['bundle']['hash']:
                    raise ValueError('Adapter changed; reconnect and validate again')
                feedback = await self.feedback(s)
                self.check_feedback(s,feedback)
                s['feedback'] = feedback
                s['touched'] = time.monotonic()
                if s['mode']=='live' and s['armed_until'] and s['armed_until'] <= time.monotonic():
                    await self.stop_session(s)
                return self.public(s)
            except Exception:
                s['armed_until'] = 0
                s['connection_validated'] = False
                with contextlib.suppress(Exception):
                    await self.stop_session(s)
                raise

    async def validate(self,sid):
        s = self.get(sid)
        await self.cancel_named(s)
        async with s['lock']:
            result = await self.stop_session(s)
            feedback = s['feedback']
            self.check_feedback(s,feedback)
            if not result['stopped_verified'] or (s['mode']=='live' and not (feedback.get('ready') and feedback.get('stop_supported'))):
                raise ValueError('Connection readiness and measured stopped state could not be validated')
            s['connection_validated'] = True
            s['touched'] = time.monotonic()
            return self.public(s)

    async def arm(self,sid):
        s = self.get(sid)
        async with s['lock']:
            if s['mode'] != 'live' or not s['connection_validated']:
                raise ValueError('Validate the physical connection before arming')
            feedback = await self.feedback(s)
            self.check_feedback(s,feedback)
            if not feedback.get('ready') or not feedback.get('stopped'):
                raise ValueError('A ready, measured stopped state is required to arm')
            bundle = self.registry.get(s['bundle']['id'])
            if bundle['hash'] != s['bundle']['hash'] or bundle['reviewed_hash'] != bundle['hash'] or not bundle['test_report']['passed']:
                raise ValueError('Adapter changed; reconnect and review')
            s['feedback'],s['armed_until'],s['touched'] = feedback,time.monotonic()+30,time.monotonic()
            return self.public(s)

    async def command(self,sid,positions=None,standard_command=None):
        s = self.get(sid)
        async with s['lock']:
            if s.get('command_job') and not s['command_job'].done():
                raise ValueError('A named command is running; Stop it before sending joint setpoints')
            s['stop_requested'],s['stopped_verified'] = False,False
            try:
                if self.registry.get(s['bundle']['id'])['hash'] != s['bundle']['hash']:
                    raise ValueError('Adapter changed; reconnect and validate again')
                feedback = await self.feedback(s)
                self.check_feedback(s,feedback)
                if s['mode']=='live' and (s['armed_until']<=time.monotonic() or not s['connection_validated']):
                    raise ValueError('Arm the validated physical connection before sending a command')
                if standard_command is not None:
                    if 'standard_contract' not in s['bundle']:raise ValueError('Generate, review and test an adapter with a standardized command contract first')
                    from services.commands.standard import resolve_command
                    _,instances,models,_=self.context(s)
                    index=next(n for n,i in enumerate(instances) if i['instance']['id']==s['robot_id'])
                    instance=instances[index]
                    if 'preview_base' in s:instance={**instance,'base_pose':s['preview_base']}
                    positions=resolve_command(with_base(models[index],instance),feedback['positions'],standard_command)
                validate_positions({'actuators':{'actuators':s['bundle']['controls']}},positions)
                duration = .5
                for key,a in s['bundle']['controls'].items():
                    delta = abs(positions[key]-feedback['positions'][key])
                    if s['mode']=='live' and delta > (.15 if a['unit']=='rad' else .01)+1e-9:
                        raise ValueError('Live manual commands are limited to 0.15 rad or 0.01 m per command')
                    duration = max(duration,1.95*delta/a['velocity'],math.sqrt(6.2*delta/a['acceleration']))
                if s['stop_requested']:
                    raise ValueError('Manual command cancelled before execution')
                if s['mode']=='environment':
                    _,_,_,environment,_ = await self.controller.context(s['project_id'],s['robot_id'])
                    if any(environment.held_objects.values()):
                        raise ValueError('Reset the held object before using manual environment controls')
                    states = await self.controller.states(environment)
                    count = max(12,math.ceil(duration*30))
                    frames = []
                    for n in range(count+1):
                        t=n/count
                        blend=10*t**3-15*t**4+6*t**5
                        q={key:value+(positions[key]-value)*blend for key,value in feedback['positions'].items()}
                        cell={rid:(q if rid==s['robot_id'] else state.positions) for rid,state in states.items()}
                        frames.append(Frame(time=n/30,step_id='manual',positions=q,objects=object_map(environment.objects),robot_positions=cell))
                    validate_trajectory(environment.models[s['robot_id']],frames,environment.objects)
                    validate_cell(frames,environment.models,environment.objects)
                    for frame in frames[1:]:
                        if s['stop_requested']:
                            break
                        if environment.remote:
                            await environment.remote.advance(frame.robot_positions,1/30)
                        else:
                            await environment.adapters[s['robot_id']].command(frame.positions)
                            await asyncio.sleep(1/30)
                    await environment.adapters[s['robot_id']].request_stop()
                    s['feedback'] = await self.feedback(s)
                    s['stopped_verified'] = s['feedback']['stopped']
                    await self.controller.persist_state(s['project_id'])
                else:
                    s['feedback'] = await s['process'].request({'operation':'command','positions':positions,'duration':duration})
                    self.check_feedback(s,s['feedback'])
                    s['stopped_verified'] = s['feedback']['stopped']
                s['touched'] = time.monotonic()
                return self.public(s)
            except Exception:
                s['armed_until'] = 0
                s['connection_validated'] = False
                with contextlib.suppress(Exception):
                    await self.stop_session(s)
                raise

    async def named_command(self,sid,command_id,arguments):
        s=self.get(sid)
        if s['mode']!='test':
            raise ValueError('Named command recipes are available only in isolated built-in simulator tests')
        async with s['lock']:
            if s.get('command_job') and not s['command_job'].done():
                raise ValueError('A command is already running')
            bundle=self.registry.get(s['bundle']['id'])
            if bundle['hash']!=s['bundle']['hash'] or bundle['reviewed_hash']!=bundle['hash'] or not (bundle.get('test_report') or {}).get('passed'):
                raise ValueError('Review and pass contract tests before testing named commands')
            definition=next((c for c in bundle.get('commands',[]) if c['id']==command_id),None)
            if definition is None:
                raise ValueError('Unknown adapter command')
            command=AdapterCommand.model_validate(definition)
            feedback=await self.feedback(s);self.check_feedback(s,feedback)
            frames=compile_recipe(command,arguments,feedback['positions'],bundle['controls'])
            _,instances,models,_=self.context(s)
            model=next(m for m,i in zip(models,instances) if i['instance']['id']==s['robot_id'])
            geometry=supports_model(model)
            if geometry:
                isolated=with_base(model,{'base_pose':{'x':0.,'y':0.,'z':0.,'yaw':0.}})
                trajectory=[Frame(time=0,step_id=command.id,positions=feedback['positions'],objects={})]
                elapsed=0.
                for frame in frames:
                    if frame['duration']:
                        elapsed+=frame['duration']
                        trajectory.append(Frame(time=elapsed,step_id=command.id,positions=frame['positions'],objects={}))
                if len(trajectory)>1: validate_trajectory(isolated,trajectory,[])
            s['command_cancel'].clear()
            s['stop_requested'],s['stopped_verified']=False,False
            s['touched']=time.monotonic()
            s['command_run']={'id':uuid.uuid4().hex[:12],'adapter_id':bundle['id'],'adapter_hash':bundle['hash'],'command_id':command.id,'status':'running','arguments':arguments,
                'progress':0.,'current_step':0,'started_at':now(),'finished_at':None,'trace':[],
                'scope':'built_in_kinematic_simulator' if geometry else 'simulated_joint_transport_only','hardware_validated':False,'error':None}
            s['command_job']=asyncio.create_task(self._run_named(s,frames))
            return self.public(s)

    async def _run_named(self,s,frames):
        report=s['command_run']
        try:
            for index,frame in enumerate(frames):
                if s['stop_requested'] or s['command_cancel'].is_set():
                    report['status']='cancelled';break
                async with s['lock']:
                    if s['stop_requested']: report['status']='cancelled';break
                    if self.registry.get(s['bundle']['id'])['hash']!=s['bundle']['hash']:
                        raise ValueError('Adapter changed during command test')
                    request={'operation':frame['operation'] if frame['operation'] in {'stop','feedback'} else 'command' if frame['operation']=='command' else 'state'}
                    if request['operation']=='feedback':request['operation']='state'
                    if request['operation']=='command': request['positions']=frame['positions']
                    feedback=await s['process'].request(request)
                    self.check_feedback(s,feedback)
                    if any(abs(feedback['positions'][key]-value)>1e-8 for key,value in frame['positions'].items()):
                        raise ValueError('Simulated feedback did not match the command recipe')
                    s['feedback']=feedback;s['stopped_verified']=feedback['stopped']
                    report['progress']=(index+1)/len(frames);report['current_step']=frame['step_index']+1
                    if index==len(frames)-1 or frames[index+1]['step_index']!=frame['step_index']:
                        report['trace'].append({'step':frame['step_index']+1,'feedback':feedback})
                if frame['duration']:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(s['command_cancel'].wait(),frame['duration'])
            else:
                report['status']='passed'
        except asyncio.CancelledError:
            report['status']='cancelled'
        except Exception as error:
            report['status']='failed';report['error']=str(error)
        finally:
            async with s['lock']:
                try:
                    feedback=await s['process'].request({'operation':'stop'})
                    self.check_feedback(s,feedback)
                    s['feedback']=feedback;s['stopped_verified']=feedback['stopped']
                    if not s['stopped_verified']:raise ValueError('Adapter did not confirm stopped feedback')
                except Exception as error:
                    s['stopped_verified']=False;report['status']='failed';report['error']=str(error)
                report['finished_at']=now();report['stopped_verified']=s['stopped_verified']
                try:self.registry.record_command_test(s['bundle']['id'],dict(report))
                except Exception as error:
                    report['status']='failed';report['error']=str(error)

    async def cancel_named(self,s):
        job=s.get('command_job')
        if job and not job.done():
            s['stop_requested']=True;s['command_cancel'].set()
            await job

    async def stop_session(self,s):
        s['stop_requested'],s['armed_until'] = True,0
        s['stopped_verified'] = False
        if s['mode']=='environment':
            environment = self.controller.sessions[s['project_id']]
            await environment.adapters[s['robot_id']].request_stop()
            s['feedback'] = await self.feedback(s)
        else:
            s['feedback'] = await s['process'].request({'operation':'stop'})
        self.check_feedback(s,s['feedback'])
        s['stopped_verified'] = s['feedback']['stopped']
        return self.public(s)

    async def stop(self,sid):
        s = self.get(sid)
        await self.cancel_named(s)
        s['stop_requested'],s['armed_until'] = True,0
        # Mark immediately, allowing a long simulator command to exit its loop.
        async with s['lock']:
            return await self.stop_session(s)

    async def close_session(self,sid):
        s = self.get(sid)
        await self.cancel_named(s)
        s['stop_requested'],s['armed_until'] = True,0
        async with s['lock']:
            try:
                await self.stop_session(s)
                if not s['stopped_verified']:
                    raise ValueError('Stop is unconfirmed; ownership is retained until a stop can be verified')
            except Exception:
                s['connection_validated'] = False
                raise
            if s['mode']=='live':
                await s['process'].request({'operation':'disconnect'})
            await s['process'].close()
            self.controller.resources.release(sid)
            del self.sessions[sid]
        return {'disconnected':True}

    async def expire(self):
        while True:
            await asyncio.sleep(1)
            for sid,s in list(self.sessions.items()):
                if time.monotonic()-s['touched']>15:
                    with contextlib.suppress(Exception):
                        await self.close_session(sid)

    async def close(self):
        if self.watchdog:
            self.watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.watchdog
        for sid in list(self.sessions):
            s = self.sessions[sid]
            with contextlib.suppress(Exception):
                await self.close_session(sid)
            await s['process'].close()

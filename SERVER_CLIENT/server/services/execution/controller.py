"""Validated cell execution with one timeline, explicit assignments and observed outcomes."""
import asyncio
import contextlib
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from shared.models.domain import Lifecycle, Log, Plan, Run, WorldObject, Frame, now
from robot_system.registry.models.demo_arm.adapters.mock.adapter import MockAdapter
from robot_system.registry.models.demo_arm.adapters.isaac_sim.adapter import IsaacCell, IsaacRobot, WorkerUnavailable
from services.api.storage import Storage, atomic_json, fingerprint
from services.planning.kinematics import forward, with_base
from services.planning.workflow import validate_cell
from services.task_engine.graph import can_transition, topological_order
from services.validation.registry import ROOT, read_yaml, resolve_adapter, validate_positions
from services.validation.trajectory import validate_trajectory
from services.world_model.world import contained, object_map
from services.execution.resources import ResourceLeases, environment_resource


@dataclass
class Session:
    adapters: dict
    objects: list[WorldObject]
    instances: dict
    models: dict
    backend: str = 'mock'
    remote: IsaacCell | None = None
    held_objects: dict = field(default_factory=dict)
    base_poses: dict = field(default_factory=dict)
    held_tools: dict = field(default_factory=dict)

    @property
    def adapter(self):
        return next(iter(self.adapters.values()))
    @property
    def held_object(self):
        return self.held_objects.get(next(iter(self.adapters)))
    @held_object.setter
    def held_object(self,value):
        self.held_objects[next(iter(self.adapters))] = value


class SimulationController:
    def __init__(self, storage: Storage, speed: float = 1., command_timeout: float = 2., remote_factory=IsaacCell):
        self.storage,self.speed,self.command_timeout = storage,speed,command_timeout
        self.remote_factory = remote_factory
        from integrations.gcp.lifecycle import GpuLifecycle
        self.gpu = GpuLifecycle(storage)
        from integrations.local_isaac import LocalIsaac
        self.local_isaac = LocalIsaac(storage)
        from integrations.nebius.tunnel import NebiusTunnel
        self.nebius = NebiusTunnel(storage)
        self.sessions,self.runs,self.jobs,self.leases = {},{},{},{}
        self.context_locks = {}
        self.offline = {}
        self.switch_lock=asyncio.Lock()
        self.switching=set()
        self.resources = ResourceLeases()
        from services.ai_orchestrator.llm import LLMRegistry
        self.llm = LLMRegistry(storage)
        from services.execution.recordings import Recordings
        self.recordings = Recordings(self)

    def ensure_idle(self,project_id):
        if project_id in self.leases:
            raise ValueError('This project has an active simulation. Stop it before changing the scene or plan.')
        backend = self.sessions[project_id].backend if project_id in self.sessions else self.storage.load_project(project_id)[0].get('simulation',{}).get('adapter','mock')
        self.resources.ensure_free([environment_resource(project_id,backend)])

    def configured_preview(self,project_id):
        from shared.models.domain import RobotState
        project,instances,models,objects=self.storage.load_project(project_id)
        ids=[i['instance']['id'] for i in instances]
        models={rid:with_base(m,i) for rid,m,i in zip(ids,models,instances)}
        session=Session(dict.fromkeys(ids),objects,dict(zip(ids,instances)),models,project.get('simulation',{}).get('adapter','mock'),held_objects=dict.fromkeys(ids))
        states={i['instance']['id']:RobotState(instance_id=i['instance']['id'],positions=i['initial_configuration']['actuator_positions'],source='simulation',connected=False) for i in instances}
        return session,states

    async def context(self,project_id,robot_id=None,scene_transfer=None):
        if project_id in self.switching and scene_transfer is None:
            raise ValueError('Simulator scene transfer is in progress')
        if project_id in self.offline:
            raise ValueError('Environment disconnected; connect the simulator in Environment first')
        async with self.context_locks.setdefault(project_id,asyncio.Lock()):
            project,instances,raw_models,initial_objects = self.storage.load_project(project_id)
            if scene_transfer is not None:initial_objects=scene_transfer['objects']
            ids = [i['instance']['id'] for i in instances]
            if not ids or len(set(ids)) != len(ids):
                raise ValueError('Projects require distinct robot instance IDs')
            models = {rid:with_base(m,i) for rid,m,i in zip(ids,raw_models,instances)}
            backend = project.get('simulation',{}).get('adapter','mock')
            if backend not in {'mock','isaac_sim'}:
                raise ValueError('Unknown simulation adapter')
            if project_id not in self.sessions:
                for rid,m in models.items():
                    if backend!='isaac_sim':resolve_adapter(m,backend,'trajectory_execution')
                    # Native connect validates the exact deployed model, USD limits and mappings.
                    # Imported metadata alone does not grant physical execution.
                session = Session({},initial_objects,dict(zip(ids,instances)),models,backend,held_objects=dict.fromkeys(ids))
                if backend == 'isaac_sim':
                    if self.remote_factory is IsaacCell:
                        from services.api.isaac import worker_configuration
                        settings=worker_configuration(self.storage)
                        if self.gpu.enabled() and self.gpu.state['status']!='ready':raise ValueError('GPU is stopped or not connected. Start GPU processing or explicitly connect the simulator first.')
                        if settings['deployment']=='nebius':await self.nebius.ensure()
                        room_path=self.storage.project_folder(project_id)/'environment/room.json'
                        room=json.loads(room_path.read_text()) if room_path.exists() else None
                        if room:room={k:v for k,v in room.items() if k not in {'proxy_ids','capture_id'}}
                        cell=IsaacCell(project_id,instances,models,initial_objects,url=settings['url'],token=settings['token'],load_scene=True if scene_transfer is not None else settings['load_scene'],room=room,
                            transfer_positions=scene_transfer['positions'] if scene_transfer is not None else None)
                        from services.api.assets import asset_record
                        cell.asset_provider=lambda digest:asset_record(self.storage,project_id,digest)
                        from simulation.isaac_sim.robot_packages import package_model
                        cell.robot_package_provider=lambda model:package_model(self.storage,model)
                        if room:
                            from services.api.storage import safe_id
                            reference=json.loads(room_path.read_text())
                            capture=reference.get('capture_id')
                            if capture:cell.room_asset_path=self.storage.runtime/'rooms'/safe_id(project_id)/safe_id(capture)/'scene.usdz'
                    else:cell = self.remote_factory(project_id,instances,models,initial_objects)
                    if scene_transfer is not None and isinstance(cell,IsaacCell):
                        cell.load_scene=True
                        cell.transfer_positions=scene_transfer['positions']
                    try:
                        await cell.connect()
                        if scene_transfer is not None and not isinstance(cell,IsaacCell):
                            await cell.reset(scene_transfer['positions'],initial_objects)
                    except BaseException:
                        with contextlib.suppress(Exception):
                            await cell.disconnect()
                        await cell.client.aclose()
                        raise
                    session.remote = cell
                    session.adapters = {rid:IsaacRobot(cell,rid,models[rid]) for rid in ids}
                    session.objects = cell.latest.objects
                else:
                    for rid,i in zip(ids,instances):
                        adapter = MockAdapter(models[rid],i)
                        await adapter.connect()
                        session.adapters[rid] = adapter
                    path = self.storage.runtime/'states'/f'{project_id}.json'
                    if scene_transfer is not None:
                        for rid,q in scene_transfer['positions'].items():
                            validate_positions(models[rid],q)
                            await session.adapters[rid].command(q)
                            await session.adapters[rid].request_stop()
                    elif path.exists():
                        saved = json.loads(path.read_text())
                        # Restore only simulation state for this exact registered robot set.
                        positions = saved.get('robots',{}) or ({ids[0]:saved['positions']} if len(ids)==1 and 'positions' in saved else {})
                        if set(positions) == set(ids):
                            for rid,q in positions.items():
                                validate_positions(models[rid],q)
                                await session.adapters[rid].command(q)
                                await session.adapters[rid].request_stop()
                            session.objects = [WorldObject.model_validate(o) for o in saved['objects']]
                            session.held_objects = saved.get('held_objects',dict.fromkeys(ids))
                            session.base_poses=saved.get('base_poses',{});session.held_tools=saved.get('held_tools',{})
                            if 'held_object' in saved:
                                session.held_object = saved['held_object']
                self.sessions[project_id] = session
            session = self.sessions[project_id]
            if set(session.adapters) != set(ids) or session.backend != backend:
                raise ValueError('Robot registry or adapter changed; reconnect/reset the simulation session')
            # Saving desired initial values never changes measured state.
            session.instances,session.models = dict(zip(ids,instances)),models
            for rid,pose in session.base_poses.items():session.models[rid]['base_pose']=pose
            if not session.remote:
                for rid in ids:
                    session.adapters[rid].model = models[rid]
            if session.remote:
                try:
                    observation = await session.remote.observe()
                except ValueError as error:
                    if 'lease expired' not in str(error):
                        raise
                    await session.remote.connect()
                    observation = session.remote.latest
                session.objects = observation.objects
                states = observation.states
            else:
                states = dict(zip(ids,await asyncio.gather(*(asyncio.wait_for(a.get_state(),self.command_timeout) for a in session.adapters.values()))))
            selected = robot_id or ids[0]
            if selected not in states:
                raise ValueError(f'Unknown robot instance: {selected}')
            return project,session.instances[selected],models[selected],session,states[selected]

    async def switch_backend(self,project_id,backend):
        """Hand off one stopped scene, committing the choice only on success.

        Saved starting configurations and historical runs are never rewritten.
        Existing fixed-scene attach remains read-only when reconnecting the same backend.
        """
        import copy
        import yaml
        from services.api.isaac import worker_configuration
        async with self.switch_lock:
            self.recordings.guard(project_id)
            self.ensure_idle(project_id)
            if backend not in {'mock','isaac_sim'}:raise ValueError('Choose mock or isaac_sim')
            path=self.storage.project_folder(project_id)/'project.yaml'
            original=path.read_text();project=read_yaml(path)
            previous=project.get('simulation',{}).get('adapter','mock')
            offline=self.offline.get(project_id)
            self.resources.ensure_free([environment_resource(project_id,backend)])
            existing=self.sessions.get(project_id) or (offline[0] if offline else None)
            if previous!=backend and existing and any(existing.held_objects.values()):
                raise ValueError('Release held objects before switching simulators; grasp constraints cannot be transferred')
            if backend=='isaac_sim':
                if worker_configuration(self.storage)['deployment']=='local':await self.local_isaac.ensure_running()
                else:await self.gpu.ensure_running()
            self.ensure_idle(project_id)
            self.resources.ensure_free([environment_resource(project_id,backend)])
            if backend==previous:
                self.offline.pop(project_id,None)
                try:await self.context(project_id)
                except BaseException:
                    if offline:self.offline[project_id]=offline
                    raise
                return {'adapter':backend,'connected':True,'scene_transferred':False}
            warning=None
            if offline:
                session,states=offline
                warning='Transferred the last observed scene from the disconnected simulator.'
            else:
                try:
                    *_,session,_=await self.context(project_id)
                    states=await self.states(session)
                except WorkerUnavailable:
                    if backend!='mock':raise
                    # A dead GPU must not trap the user. Fall back explicitly to
                    # the saved scene, never claim stale GPU feedback was transferred.
                    session,states=self.configured_preview(project_id)
                    warning='Isaac Sim was unreachable. Opened the saved starting scene; current GPU poses could not be transferred.'
            if any(session.held_objects.values()):raise ValueError('Release held objects before switching simulators; grasp constraints cannot be transferred')
            if not all(s.stopped for s in states.values()):raise ValueError('Stop every robot before switching simulators')
            transfer={'positions':{rid:dict(s.positions) for rid,s in states.items()},'objects':copy.deepcopy(session.objects)}
            owner='scene-transfer:'+uuid.uuid4().hex
            # Acquire before disconnecting: another project/control session can
            # win ownership while observations are awaited. It must never leave
            # this project disconnected on a rejected acquisition.
            self.resources.acquire([environment_resource(project_id,previous),environment_resource(project_id,backend)],owner)
            self.switching.add(project_id)
            try:
                if not session.remote and not offline and not warning:
                    atomic_json(self.storage.runtime/'states'/f'{project_id}.json',{'robots':transfer['positions'],
                        'objects':[o.model_dump(mode='json') for o in transfer['objects']], 'held_objects':session.held_objects,'base_poses':session.base_poses,'held_tools':session.held_tools,'source':'simulation'})
                try:await self._disconnect_session(project_id)
                except WorkerUnavailable:pass
                self.offline.pop(project_id,None)
                updated=copy.deepcopy(project);updated['simulation']={**updated.get('simulation',{}),'adapter':backend}
                path.write_text(yaml.safe_dump(updated,sort_keys=False))
                await self.context(project_id,scene_transfer=transfer)
                if backend=='mock':
                    atomic_json(self.storage.runtime/'states'/f'{project_id}.json',{'robots':transfer['positions'],
                        'objects':[o.model_dump(mode='json') for o in transfer['objects']], 'held_objects':dict.fromkeys(states),'source':'simulation'})
            except BaseException:
                path.write_text(original)
                failed=self.sessions.pop(project_id,None)
                if failed:
                    with contextlib.suppress(Exception):
                        if failed.remote:await failed.remote.disconnect()
                        else:await asyncio.gather(*(a.disconnect() for a in failed.adapters.values()))
                if offline:self.offline[project_id]=offline
                elif previous=='mock':
                    # The old built-in session is still an exact, stopped snapshot.
                    for adapter in session.adapters.values():await adapter.connect()
                    self.sessions[project_id]=session
                else:
                    # A closed native transport must be explicitly reconnected;
                    # retain its last observation instead of fabricating connectivity.
                    self.offline[project_id]=(session,{rid:s.model_copy(update={'connected':False}) for rid,s in states.items()})
                raise
            finally:
                self.switching.discard(project_id)
                self.resources.release(owner)
            return {'adapter':backend,'connected':True,'scene_transferred':not bool(warning and not offline),'robots':len(states),'objects':len(transfer['objects']),'warning':warning}

    async def states(self,session):
        if session.remote:
            observation = await session.remote.observe()
            session.objects = observation.objects
            return observation.states
        states=dict(zip(session.adapters,await asyncio.gather(*(asyncio.wait_for(a.get_state(),self.command_timeout) for a in session.adapters.values()))))
        return {rid:s.model_copy(update={'base_pose':session.base_poses.get(rid,session.instances[rid].get('base_pose'))}) for rid,s in states.items()}

    async def snapshot(self,project_id):
        project,instance,model,session,state = await self.context(project_id)
        states = await self.states(session)
        return {'project':project,'instance':instance,'model':model,'instances':session.instances,'models':session.models,
                'world':[o.model_dump(mode='json') for o in session.objects],'positions':state.positions,
                'robot_positions':{rid:s.positions for rid,s in states.items()},'held_objects':session.held_objects,
                'base_poses':{rid:s.base_pose for rid,s in states.items()},
                'runtime_version':'0.4.0-robotics-v2','adapter':session.backend,
                'llm_adapters':self.llm.snapshot(),
                'motion_worker':__import__('services.planning.motion_client',fromlist=['MotionClient']).MotionClient(self.storage).configuration(),
                'llm_roles':__import__('services.ai_orchestrator.two_stage',fromlist=['settings']).settings(self.llm).model_dump(),
                'worker':session.remote.metadata if session.remote else None,
                'worker_session_id':session.remote.session_id if session.remote else None,
                'room':json.loads((self.storage.project_folder(project_id)/'environment/room.json').read_text()) if (self.storage.project_folder(project_id)/'environment/room.json').exists() else None,
                'task_library':{p.stem:read_yaml(p) for p in sorted((ROOT/'task_library/manipulation').glob('*.yaml'))}}

    async def persist_state(self,project_id):
        _,_,_,session,_ = await self.context(project_id)
        if session.remote:
            return  # A reconnect must read the GPU scene, never replay saved mock positions.
        states = await self.states(session)
        atomic_json(self.storage.runtime/'states'/f'{project_id}.json',{'robots':{rid:s.positions for rid,s in states.items()},
            'objects':[o.model_dump(mode='json') for o in session.objects],'held_objects':session.held_objects,'base_poses':session.base_poses,'held_tools':session.held_tools,'source':'simulation'})

    async def disconnect(self,project_id):
        self.recordings.guard(project_id)
        self.ensure_idle(project_id)
        await self._disconnect_session(project_id)

    async def _disconnect_session(self,project_id):
        # Caller holds ownership or has just passed ensure_idle. The hand-off
        # transaction owns both simulator resources while closing the old one.
        session = self.sessions.pop(project_id,None)
        if session:
            if session.remote:
                await session.remote.disconnect()
            else:
                await asyncio.gather(*(a.disconnect() for a in session.adapters.values()))

    async def reset(self,project_id):
        self.recordings.guard(project_id)
        self.ensure_idle(project_id)
        project,instances,_,objects = self.storage.load_project(project_id)
        if project.get('simulation',{}).get('adapter') == 'isaac_sim':
            *_,session,_ = await self.context(project_id)
            await session.remote.reset({i['instance']['id']:i['initial_configuration']['actuator_positions'] for i in instances},objects)
            session.held_objects = dict.fromkeys(session.adapters)
        else:
            await self.disconnect(project_id)
            (self.storage.runtime/'states'/f'{project_id}.json').unlink(missing_ok=True)
        return await self.context(project_id)

    def transition(self,run,target):
        if not can_transition(run.status,target):
            raise RuntimeError(f'Invalid task transition: {run.status} -> {target}')
        run.history.append({'from':run.status.value,'to':target.value,'timestamp':now()})
        run.status = target

    def cell_frames(self,plan,states):
        primary = plan.task.robot_id
        frames = []
        for frame in plan.frames:
            positions = frame.robot_positions or {rid:(frame.positions if rid==primary else s.positions) for rid,s in states.items()}
            if set(positions) != set(states):
                raise ValueError('Plan timeline must include every robot, including idle robots')
            frames.append(frame.model_copy(update={'robot_positions':positions,'held_objects':frame.held_objects or {rid:(frame.held_object if rid==primary else None) for rid in states},
                                                  'active_steps':frame.active_steps or {primary:frame.step_id}}))
        return frames

    async def execute_registered_plan(self,plan_id,expected_fingerprint,project_id=None,adapter=None):
        if project_id is None:
            from services.api.storage import safe_id
            matches = list(self.storage.projects.glob(f'*/plans/*/revisions/{safe_id(plan_id)}/plan.json'))
            if not matches:
                matches = list(self.storage.projects.glob(f'*/tasks/{safe_id(plan_id)}/plan.json'))
            if len(matches)!=1:
                raise ValueError('Plan must resolve to exactly one project')
            project_id = matches[0].parents[4].name if 'revisions' in matches[0].parts else matches[0].parents[2].name
        self.ensure_idle(project_id)
        plan = self.storage.get_plan(project_id,plan_id)
        if not plan.valid or not plan.frames or any(c.status=='failed' for c in plan.checks):
            raise ValueError('Plan validation failed; correct the reported issues before simulation')
        if plan.definition_id:
            definition = self.storage.get_definition(project_id,plan.definition_id)
            if definition.version != plan.definition_version or self.storage.definition_archived(project_id,definition.id):
                raise ValueError('This plan revision is stale; compile the edited plan again')
        snapshot = await self.snapshot(project_id)
        session = self.sessions[project_id]
        if any(m.get('binding_stale') for m in session.models.values()):raise ValueError('Robot mapping is stale; select a current published binding and compile again')
        if adapter and adapter != session.backend or plan.adapter != session.backend:
            raise ValueError('Plan adapter does not match the connected simulation; generate a new plan')
        if session.remote and plan.motion_manifest.get('schema_version')==2 and any(g['kind'] in {'grasp','release'} for t in plan.motion_manifest.get('tasks',[]) for g in t['normalized']) and not session.remote.metadata.get('attachment_feedback'):
            raise ValueError('This Isaac worker does not provide verified grasp-contact feedback for the new task contract. Use the built-in ideal preview or validate a native contact-feedback integration first')
        if plan.fingerprint != expected_fingerprint or fingerprint(snapshot) != plan.fingerprint:
            raise ValueError('This plan is stale. Robot state or project configuration changed; generate and validate a new plan.')
        if any(session.held_objects.values()):
            raise ValueError('The preview has a held object from an interrupted run. Reset the scene before replanning.')
        states = await self.states(session)
        frames = self.cell_frames(plan,states)
        topological_order(plan.task.steps)
        if not plan.atomic_tasks or any(t.operation != 'llm' for t in plan.atomic_tasks):
            if plan.motion_manifest.get('schema_version')==2:
                from services.planning.physical_checker import check_plan
                checked=await check_plan(self.motion,session.models,frames,session.objects)
                if checked.status=='failed':raise ValueError('Physical checker: '+'; '.join(f.message for f in checked.findings))
                if session.remote and not session.remote.metadata.get('mobile_base_feedback') and any(f.base_poses.get(rid,model.get('base_pose',{}))!=model.get('base_pose',{}) for rid,model in session.models.items() for f in frames):
                    raise ValueError('This Isaac worker does not yet advertise mobile-base trajectory feedback; use the built-in preview')
            else:
                for rid,model in session.models.items():
                    validate_trajectory(model,[f.model_copy(update={'positions':f.robot_positions[rid]}) for f in frames],session.objects)
                validate_cell(frames,session.models,session.objects)
        self.ensure_idle(project_id)
        run = Run(id=uuid.uuid4().hex[:12],plan_id=plan.id,project_id=project_id,adapter=session.backend,definition_id=plan.definition_id,revision_id=plan.id)
        self.resources.acquire([environment_resource(project_id,session.backend)],run.id)
        try:
            self.storage.save_run(run)
        except BaseException:
            self.resources.release(run.id)
            raise
        self.leases[project_id] = run.id
        self.runs[run.id] = run
        self.jobs[run.id] = asyncio.create_task(self._execute(run,plan,frames))
        return run

    async def stopped(self,session):
        if session.remote:
            observation = await session.remote.stop()
            session.objects = observation.objects
            return observation.states
        await asyncio.gather(*(asyncio.wait_for(a.request_stop(),self.command_timeout) for a in session.adapters.values()))
        return await self.states(session)

    def apply_preview(self,session,frame,states):
        for rid,state in states.items():
            if not session.held_objects.get(rid) and not frame.held_objects.get(rid):continue
            tool = forward(session.models[rid],state.positions,frame.held_tools.get(rid) or session.held_tools.get(rid))
            held = session.held_objects.get(rid)
            if held:
                next(o for o in session.objects if o.id==held).position = tool
            desired = frame.held_objects.get(rid)
            if desired and not held:
                if desired in session.held_objects.values():
                    raise RuntimeError('Two robots cannot own the same object')
                item = next(o for o in session.objects if o.id==desired)
                from services.commands.standard import components
                gripper=next(iter(components(session.models[rid]).values()))
                if math.dist(tuple(tool.model_dump().values()),tuple(item.position.model_dump().values()))>.012 or (session.models[rid]['actuators']['actuators'][gripper['actuator']]['unit']=='m' and state.positions[gripper['actuator']]>item.size.x+.0001):
                    raise RuntimeError(f'{rid}: observed grasp preconditions failed')
                session.held_objects[rid],item.position = desired,tool
                session.held_tools[rid]=frame.held_tools.get(rid)
            elif not desired and held:
                from services.commands.standard import components
                gripper=next(iter(components(session.models[rid]).values()))
                if abs(state.positions[gripper['actuator']]-gripper['open'])>.005:
                    raise RuntimeError(f'{rid}: gripper feedback did not confirm release')
                session.held_objects[rid] = None

    def verify(self,run,plan,session,observed):
        rid = plan.task.robot_id
        if plan.task.template=='pick_place':
            item = next(o for o in session.objects if o.id==plan.task.object_id)
            region = next(o for o in session.objects if o.id==plan.task.target_id)
            empty = session.held_objects.get(rid) is None and observed['gripper']>=.075
            success = contained(item,region) and empty
            run.evidence.update({'object':item.model_dump(mode='json'),'region':region.model_dump(mode='json'),
                'object_inside_target':contained(item,region),'gripper_empty':empty,'postcondition_passed':success,
                'observation_source':'isaac_sim_rigid_body_poses' if session.remote else 'local_preview_scene'})
        else:
            error = max(abs(observed[k]-plan.frames[-1].positions[k]) for k in observed)
            success = error<= (.03 if session.remote else .001)
            run.evidence.update({'max_joint_error':error,'postcondition_passed':success})
        if not success:
            raise RuntimeError(f'{rid}: trajectory finished, but task postconditions failed')

    def verify_atomic(self,run,plan,task_id,session,states):
        task = next(t for t in plan.atomic_tasks if t.id == task_id)
        if task.operation == 'llm':
            if task.id not in run.evidence.get('llm',{}):
                raise RuntimeError(f'{task.name}: no LLM answer recorded')
            run.task_statuses[task.id] = 'completed'
            run.evidence.setdefault('tasks',{})[task.id] = {'postcondition_passed':True,'operation':'llm','observation_source':'llm_answer'}
            return
        state = states[task.robot_id]
        success = state.connected
        tolerance = .12 if session.remote else .01
        endpoint = next(f for f in reversed(plan.frames) if task_id in f.active_steps.values())
        if task.operation in {'move','command'}:
            success = success and all(abs(state.positions[k]-v) <= tolerance for k,v in endpoint.robot_positions[task.robot_id].items())
        elif task.operation == 'grasp':
            item = next(o for o in session.objects if o.id == task.object_id)
            tool = forward(session.models[task.robot_id],state.positions)
            success = success and math.dist(tuple(tool.model_dump().values()),tuple(item.position.model_dump().values())) <= (.06 if session.remote else .015)
            # Native contacts are generated 1 mm from each surface. Allow
            # their combined separation plus solver slop, not arbitrary closure.
            contact_gap = .003 if session.remote else 0.
            success = success and state.positions['gripper'] <= item.size.x + contact_gap
        elif task.operation == 'release':
            success = success and state.positions['gripper'] >= .075 and task.object_id not in session.held_objects.values()
        elif task.object_id:
            item = next(o for o in session.objects if o.id == task.object_id)
            region = next(o for o in session.objects if o.id == task.target_id)
            from services.world_model.world import placement_satisfied
            success = success and placement_satisfied(item,region,task.placement) and state.positions['gripper'] >= .075 and task.object_id not in session.held_objects.values()
        else:
            success = success and all(abs(state.positions[k]-v) <= tolerance for k,v in endpoint.robot_positions[task.robot_id].items())
        if plan.motion_manifest.get('schema_version')==2:
            from services.world_model.world import placement_satisfied
            from services.commands.standard import components
            manifest=next(m for m in plan.motion_manifest['tasks'] if m['id']==task.id)
            for goal in manifest['normalized']:
                if goal['kind']=='grasp':success=success and session.held_objects.get(task.robot_id)==goal['object_id'] and (not session.remote or state.attachment_source in {'simulation_contact','simulation_observed_motion'} and goal['object_id'] in state.attachments)
                elif goal['kind']=='release':success=success and goal['object_id'] not in session.held_objects.values()
                elif goal['kind']=='verify':
                    item=next(o for o in session.objects if o.id==goal['object_id']);target=next(o for o in session.objects if o.id==goal['target_id'])
                    gripper=next(iter(components(session.models[task.robot_id]).values()),None)
                    success=success and placement_satisfied(item,target,goal.get('placement','inside')) and goal['object_id'] not in session.held_objects.values() and (not gripper or abs(state.positions[gripper['actuator']]-gripper['open'])<.005)
        run.evidence.setdefault('tasks',{})[task.id] = {'postcondition_passed':success,'operation':task.operation,'robot_id':task.robot_id,'observation_source':'isaac_sim' if session.remote else 'built_in_simulator'}
        if not success:
            raise RuntimeError(f'{task.name}: observed task postcondition failed')
        run.task_statuses[task.id] = 'completed'

    def verify_atomic_final(self,run,plan,session,states):
        latest = {}
        for task in plan.atomic_tasks:
            if task.operation == 'verify' and task.object_id:
                latest[task.object_id] = task
        for task in latest.values():
            self.verify_atomic(run,plan,task.id,session,states)
        if len(run.task_statuses) != len(plan.atomic_tasks):
            raise RuntimeError('Not every atomic task was verified')
        run.evidence['postcondition_passed'] = True

    async def invoke_llm_task(self,run,task,session):
        import re
        def substitute(match):
            return run.evidence['llm'][match.group(1)]['answer']
        input = re.sub(r'\{\{tasks\.([a-zA-Z0-9_:-]+)\.answer\}\}',substitute,task.llm_input)
        run.current_step = task.id
        run.logs.append(Log(level='info',message='Waiting for LLM answer; robot trajectories paused.',step_id=task.id))
        pending = asyncio.create_task(self.llm.adapter(task.llm_adapter_id)(input,task.llm_system_prompt))
        try:
            while not pending.done():
                await asyncio.wait({pending},timeout=.1)
                if run.stop_requested:
                    pending.cancel()
                    return False
                # Keep the external simulator lease fresh during a provider request.
                if session.remote:
                    await self.states(session)
            run.evidence.setdefault('llm',{})[task.id] = pending.result()
            self.storage.save_run(run)
            return True
        finally:
            if not pending.done():
                pending.cancel()
            with contextlib.suppress(asyncio.CancelledError,Exception):
                await pending

    async def _execute(self,run,plan,frames):
        session = self.sessions[run.project_id]
        completed,active = set(),set()
        verified = set()
        llm_only = bool(plan.atomic_tasks) and all(t.operation == 'llm' for t in plan.atomic_tasks)
        dispatch=None
        try:
            if plan.motion_manifest.get('schema_version')==2:
                from services.adapters.simulation_dispatch import SimulatedDispatch
                dispatch=SimulatedDispatch(self.storage,self.llm,session.models);await dispatch.open(await self.states(session))
                run.evidence['generated_driver_dispatch']={'source':'simulation','hardware_contacted':False,'bindings':{rid:m['binding']['hash'] for rid,m in session.models.items() if m.get('binding')}}
            for status in (Lifecycle.VALIDATING,Lifecycle.PLANNING,Lifecycle.PLAN_READY,Lifecycle.SIMULATING):
                self.transition(run,status)
            run.logs.append(Log(level='info',message=f'Validated {len(session.adapters)} robot(s); acquired exclusive cell lease.'))
            run.logs.append(Log(level='warning',message='Isaac Sim physics observations; no hardware authorization.' if session.remote else 'Local kinematic preview; idealized grasp, no contact physics.'))
            started,previous_time = time.monotonic(),0.
            for frame in frames:
                if run.stop_requested:
                    break
                next_active = set(frame.active_steps.values())
                for step_id in active-next_active:
                    if plan.atomic_tasks:
                        self.verify_atomic(run,plan,step_id,session,states)
                    completed.add(step_id)
                    run.step_statuses[step_id] = 'done'
                for step_id in next_active-active:
                    step = next(s for s in plan.task.steps if s.id==step_id)
                    if any(d not in completed for d in step.dependencies):
                        raise RuntimeError('Dependency was not completed before execution')
                    run.step_statuses[step_id] = 'running'
                    run.logs.append(Log(level='info',message=f'{step.robot_id or plan.task.robot_id}: {step.label}',step_id=step_id))
                    if step.operation == 'llm':
                        task = next(t for t in plan.atomic_tasks if t.id==step_id)
                        before = time.monotonic()
                        precomputed=plan.motion_manifest.get('llm_answers',{}).get(task.id)
                        if precomputed is not None:run.evidence.setdefault('llm',{})[task.id]=precomputed
                        elif not await self.invoke_llm_task(run,task,session):
                            break
                        started += time.monotonic()-before
                if run.stop_requested:
                    break
                active = next_active
                run.current_step = frame.step_id
                delay = frame.time/(1 if session.remote else self.speed)-(time.monotonic()-started)
                if delay>0:
                    await asyncio.sleep(delay)
                if run.stop_requested:
                    break
                if dispatch:frame=await dispatch.dispatch(frame)
                if session.remote:
                    if frame.time>previous_time and not llm_only:
                        observation = await session.remote.advance(frame.robot_positions,frame.time-previous_time)
                    else:
                        observation = await session.remote.observe()
                    states,session.objects = observation.states,observation.objects
                    for rid,state in states.items():
                        if state.attachment_source in {'simulation_contact','simulation_observed_motion'}:session.held_objects[rid]=state.attachments[0] if state.attachments else None
                    for rid,expected_object in frame.held_objects.items():
                        if plan.motion_manifest.get('schema_version')==2 and expected_object and rid not in frame.pending_grasps and session.held_objects.get(rid)!=expected_object:raise RuntimeError(rid+': measured object-following feedback no longer confirms the grasp')
                    # Object dynamics belong to Isaac; never synthesize attachment/poses here.
                else:
                    if not llm_only:
                        await asyncio.gather(*(asyncio.wait_for(session.adapters[rid].command(q),self.command_timeout) for rid,q in frame.robot_positions.items()))
                        session.base_poses.update(frame.base_poses)
                        for rid,pose in frame.base_poses.items():session.models[rid]['base_pose']=pose
                    states = await self.states(session)
                for rid,state in states.items():
                    validate_positions(session.models[rid],state.positions)
                    if session.remote and session.models[rid].get('mobility',{}).get('classification','STATIONARY')!='STATIONARY' and rid in frame.base_poses:
                        base=state.base_pose;expected=frame.base_poses[rid]
                        if not base or math.hypot(base['x']-expected['x'],base['y']-expected['y'])>.03 or abs(math.atan2(math.sin(base['yaw']-expected['yaw']),math.cos(base['yaw']-expected['yaw'])))>.08:raise RuntimeError(rid+': native base odometry did not track the validated navigation path')
                    for key,value in frame.robot_positions[rid].items():
                        step_id = frame.active_steps.get(rid)
                        operation = next((s.operation for s in plan.task.steps if s.id==step_id),None)
                        contact_closing = bool(frame.held_objects.get(rid)) or operation=='grasp'
                        tolerance = ((.04 if contact_closing else .015) if key=='gripper' else .12) if session.remote else (.003 if key=='gripper' else .01)
                        error=state.positions[key]-value
                        if key in session.models[rid].get('continuous_joints',[]):error=math.atan2(math.sin(error),math.cos(error))
                        if abs(error)>tolerance:
                            unit=session.models[rid]['actuators']['actuators'][key]['unit']
                            raise RuntimeError(f'{rid}/{key}: simulated joint feedback {state.positions[key]:.6g} {unit} did not track the validated command {value:.6g} {unit} (tolerance {tolerance:g} {unit})')
                if not session.remote and not llm_only:
                    self.apply_preview(session,frame,states)
                run.robot_states = states
                run.frame = frame.model_copy(update={'positions':states[plan.task.robot_id].positions,'robot_positions':{rid:s.positions for rid,s in states.items()},
                    'objects':object_map(session.objects),'held_objects':dict(session.held_objects),'held_object':session.held_objects.get(plan.task.robot_id)})
                run.elapsed,run.progress = frame.time,min(1,frame.time/plan.duration)
                previous_time = frame.time
                for task in plan.workflow_tasks:
                    if task.id not in verified and frame.time+1e-5>=task.end:
                        child_plan = plan.model_copy(update={'task':task.task,'frames':[Frame(time=task.end,step_id='verify',positions=task.final_positions,objects={})]})
                        result = Run(id=run.id,plan_id=plan.id,project_id=run.project_id)
                        self.verify(result,child_plan,session,states[task.robot_id].positions)
                        run.evidence.setdefault('tasks',{})[task.id] = result.evidence
                        run.task_statuses[task.id] = 'completed'
                        verified.add(task.id)
            final_states = await self.stopped(session)
            run.robot_states = final_states
            run.stopped_verified = all(s.stopped for s in final_states.values())
            if not run.stopped_verified:
                raise RuntimeError('One or more adapters did not confirm a stopped state')
            if run.frame:
                run.frame = run.frame.model_copy(update={'objects':object_map(session.objects),'robot_positions':{rid:s.positions for rid,s in final_states.items()},'positions':final_states[plan.task.robot_id].positions})
            if run.stop_requested:
                self.transition(run,Lifecycle.CANCELLED)
                run.logs.append(Log(level='warning',message='Cancellation requested; stopped state confirmed for every robot.'))
            else:
                self.transition(run,Lifecycle.VERIFYING)
                if plan.atomic_tasks:
                    for step_id in active:
                        self.verify_atomic(run,plan,step_id,session,final_states)
                    self.verify_atomic_final(run,plan,session,final_states)
                elif plan.workflow_tasks:
                    if len(verified)!=len(plan.workflow_tasks):
                        raise RuntimeError('Not every workflow task was verified')
                    # After the final stop/settling, recheck the last destination for each
                    # object. Earlier checkpoints alone cannot prove the final scene.
                    last_objects = {}
                    last_robots = {}
                    for task in plan.workflow_tasks:
                        last_robots[task.robot_id] = task
                        if task.task.object_id:
                            last_objects[task.task.object_id] = task
                    final_objects = {}
                    for object_id,task in last_objects.items():
                        item = next(o for o in session.objects if o.id==object_id)
                        region = next(o for o in session.objects if o.id==task.task.target_id)
                        final_objects[object_id] = contained(item,region) and object_id not in session.held_objects.values()
                    for rid,task in last_robots.items():
                        if task.task.template=='move_home':
                            if any(abs(final_states[rid].positions[k]-v)>(.03 if session.remote else .001) for k,v in task.final_positions.items()):
                                raise RuntimeError(f'{rid}: final home state changed during settling')
                    run.evidence['final_object_postconditions'] = final_objects
                    if not all(final_objects.values()):
                        raise RuntimeError('Final scene changed after task checkpoints; object placement was not preserved')
                    run.evidence['postcondition_passed'] = True
                else:
                    self.verify(run,plan,session,final_states[plan.task.robot_id].positions)
                for step_id in active:
                    run.step_statuses[step_id]='done'
                self.transition(run,Lifecycle.SIMULATION_PASSED)
                run.progress = 1.
                run.logs.append(Log(level='success',message='Simulation postconditions verified from observed state. Hardware remains unauthorized.'))
        except asyncio.CancelledError:
            run.status = Lifecycle.CANCELLED
            run.logs.append(Log(level='warning',message='Runtime shutting down; simulation cancelled.'))
            with contextlib.suppress(Exception):
                run.stopped_verified = all(s.stopped for s in (await self.stopped(session)).values())
        except Exception as error:
            run.status = Lifecycle.TIMED_OUT if isinstance(error,TimeoutError) else Lifecycle.FAILED
            run.logs.append(Log(level='error',message=str(error) or 'Adapter command timed out'))
            with contextlib.suppress(Exception):
                run.stopped_verified = all(s.stopped for s in (await self.stopped(session)).values())
        finally:
            if dispatch:
                confirmed=await dispatch.close()
                if not confirmed:
                    run.stopped_verified=False;run.status=Lifecycle.FAILED;run.logs.append(Log(level='error',message='Generated adapter did not confirm stopped simulated feedback'))
            run.finished_at = now()
            run.evidence.update({'scope':'isaac_sim_observed' if session.remote else 'kinematic_preview','physics_validated':False,
                'physics_simulated':bool(session.remote and session.remote.metadata.get('engine')=='isaac_sim'),
                'worker':session.remote.metadata if session.remote else None,'hardware_authorized':False,
                'stop_requested':run.stop_requested,'stopped_verified':run.stopped_verified})
            with contextlib.suppress(Exception):
                await self.persist_state(run.project_id)
            try:
                self.storage.save_run(run)
            finally:
                self.leases.pop(run.project_id,None);self.resources.release(run.id)

    def stop(self,run_id):
        run = self.runs.get(run_id) or self.storage.get_run(run_id)
        if not run.finished_at:
            run.stop_requested = True
            run.logs.append(Log(level='warning',message='Stop requested; waiting for every robot to confirm.'))
        return run

    async def close(self):
        for job in self.jobs.values():
            if not job.done():
                job.cancel()
        await asyncio.gather(*self.jobs.values(),return_exceptions=True)
        await self.recordings.close()
        for project_id in list(self.sessions):
            with contextlib.suppress(Exception):
                await self.disconnect(project_id)

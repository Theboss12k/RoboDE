"""Limited business API. Uses the same compiler, snapshots, scheduler and simulator leases."""
import asyncio
import uuid
from fastapi import APIRouter,HTTPException
from pydantic import Field
from shared.models.domain import Contract,PlanDefinition,now
from shared.models.robotics import RoleSettings,SceneImage
from services.api.storage import atomic_json,fingerprint,safe_id
from services.planning.definitions import compile_definition
from services.ai_orchestrator.goal_constraints import validate_goal_outcome
from services.planning.templates import expand_template
from services.ai_orchestrator.providers import get_provider
from services.business.planning import parse_transfer,transfer_tasks
import json
import os


class BusinessCommand(Contract):
    instruction:str=Field(min_length=2,max_length=4000)
    request_id:uuid.UUID
    robot_id:str|None=None
    image:SceneImage|None=None
    # Optional per-command models; empty uses the workspace Planner LLM and Task LLM.
    planner_adapter_id:str|None=None
    task_adapter_id:str|None=None


def business_router(store,controller):
    router=APIRouter(prefix='/api/business')
    locks={}
    def folder(pid):
        store.load_project(pid)
        return store.runtime/'business'/safe_id(pid)
    def read(pid,cid):return json.loads((folder(pid)/(safe_id(cid)+'.json')).read_text())
    def save(pid,data):atomic_json(folder(pid)/(data['id']+'.json'),data)
    def public(job):
        value={k:v for k,v in job.items() if k not in {'fingerprint'}}
        if job.get('physical_status') and job.get('revision_id'):
            p=store.runtime/'physical_approvals'/safe_id(job['project_id'])/(safe_id(job['revision_id'])+'.json')
            if p.exists():
                approval=json.loads(p.read_text());value['physical_status']=approval['status']
                if approval.get('run_id'):value['run_id']=approval['run_id'];value['status']='running' if approval['status']=='executing' else approval['status']
        return value

    async def prepare_semantic(pid,data,cid,cell,states,snapshot,stamp,answers=None,definition=None):
        from services.ai_orchestrator.two_stage import decompose,bind_tasks
        from services.planning.compiler_v2 import compile_v2
        import copy
        if definition is None:
            for chosen in (data.planner_adapter_id,data.task_adapter_id):
                if chosen:controller.llm.resolve(chosen)
            definition=PlanDefinition(id=uuid.uuid4().hex[:12],project_id=pid,name=data.instruction.strip()[:120],goal=data.instruction.strip(),
                role_settings=RoleSettings(planner_adapter_id=data.planner_adapter_id,binding_adapter_id=data.task_adapter_id))
        selected=copy.copy(cell)
        if data.robot_id:
            if data.robot_id not in cell.instances:raise ValueError('Selected robot is not in this workspace')
            selected.instances={data.robot_id:cell.instances[data.robot_id]};selected.models={data.robot_id:cell.models[data.robot_id]}
        proposal=await decompose(controller.llm,definition,selected,states,stamp,answers,data.image)
        definition.version+=1;definition.clarification_questions=proposal.questions;definition.planning_error=proposal.error
        definition.planning_status='tasks_ready' if proposal.status=='ready' else proposal.status
        job={'id':cid,'project_id':pid,'instruction':data.instruction.strip(),'requested_robot':data.robot_id,'definition_id':definition.id,'revision_id':None,'fingerprint':stamp,'backend':cell.backend,'robot_id':data.robot_id or next(iter(cell.instances)),'robot_name':'Assigned project robots','status':proposal.status,'duration':0.,'created_at':now(),'run_id':None,'steps':[],'checks':[],'clarification_questions':proposal.questions,'planning_error':proposal.error}
        from services.ai_orchestrator.two_stage import effective_models
        chosen=effective_models(controller.llm,definition);job['ai_models']={'planner':chosen['planner']['model'],'task':chosen['binder']['model']}
        if proposal.status=='ready':
            definition.tasks=proposal.tasks;errors=await bind_tasks(controller.llm,definition,cell,cell.objects)
            if errors:
                job.update(status='unresolved',checks=[{'status':'failed','message':e['task_id']+': '+e['error']} for e in errors])
            else:
                definition.planning_status='commands_ready'
                revision=await compile_v2(store,definition,cell,states,stamp,controller.motion)
                validate_goal_outcome(data.instruction,cell.objects,revision)
                job.update(revision_id=revision.id,status='ready' if revision.valid else 'validation_failed',duration=revision.duration,steps=[{'id':t.id,'name':t.name} for t in revision.atomic_tasks],checks=[c.model_dump() for c in revision.checks],validation_report=revision.validation_report.model_dump(mode='json') if revision.validation_report else None)
                if fingerprint(await controller.snapshot(pid))!=stamp:raise HTTPException(409,'Workspace changed during preparation; prepare the current scene again')
                store.save_definition(definition);store.save_plan(revision,snapshot)
        controller.ensure_idle(pid)
        if fingerprint(await controller.snapshot(pid))!=stamp:raise HTTPException(409,'Workspace changed during preparation; prepare the current scene again')
        if not job.get("revision_id"):store.save_definition(definition)
        save(pid,job);return public(job)

    @router.get('/projects')
    async def projects():
        return [{'id':p['id'],'name':p['name'],'description':p.get('description','')} for p in store.list_projects()]

    @router.post('/session/activity')
    async def session_activity():
        if os.getenv('ROBOT_IDE_DEPLOYMENT')=='cloud':
            from integrations.gcp.activity import touch
            touch('cloud-user')
        return {'acknowledged':True}

    @router.get('/projects/{pid}/workspace')
    async def workspace(pid:str):
        project,instances,raw_models,initial_objects=store.load_project(pid)
        preview=project.get('simulation',{}).get('adapter')=='isaac_sim' and controller.gpu.enabled() and pid not in controller.sessions and pid not in controller.offline
        if preview:
            from services.execution.controller import Session
            from services.planning.kinematics import with_base
            from shared.models.domain import RobotState
            models=[with_base(m,i) for m,i in zip(raw_models,instances)]
            states={i['instance']['id']:RobotState(instance_id=i['instance']['id'],positions=i['initial_configuration']['actuator_positions'],source='simulation',connected=False) for i in instances}
            session=Session({},initial_objects,{i['instance']['id']:i for i in instances},{i['instance']['id']:m for i,m in zip(instances,models)},'isaac_sim')
            source='configured_preview';connected=False
        elif pid in controller.offline:
            session,states=controller.offline[pid]
            project,instances,models,_=store.load_project(pid)
            source='last_observed';connected=False
        else:
            project,_,_,session,_=await controller.context(pid)
            from robot_system.registry.models.demo_arm.adapters.isaac_sim.adapter import WorkerUnavailable
            try:
                states=await controller.states(session)
                source='isaac_sim' if session.remote else 'built_in';connected=True
            except WorkerUnavailable:
                if not session.remote or not session.remote.latest:raise
                states={rid:state.model_copy(update={'connected':False}) for rid,state in session.remote.latest.states.items()}
                controller.offline[pid]=(session,states);controller.sessions.pop(pid,None)
                await session.remote.client.aclose()
                controller.gpu.state.update(status='unknown',message='GPU connection ended. Start processing again when needed.')
                source='last_observed';connected=False
            instances=list(session.instances.values());models=list(session.models.values())
        objects=[o.model_dump(mode='json') for o in session.objects]
        assets=[{**o,'planning_id':o['id'],'source':source,'read_only':False} for o in objects]
        inventory_scope='Project assets'
        if connected and session.remote:
            try:
                inventory=await session.remote.inventory()
                assets=inventory['assets'];inventory_scope=inventory.get('scope','Isaac Sim scene assets')
            except ValueError:
                inventory_scope='Tracked project assets · update the Isaac worker for full scene inventory'
        if not session.remote or not connected:
            assets += [{'id':i['instance']['id'],'planning_id':None,'name':i['instance']['name'],'category':'robot','kind':'robot','source':source,'read_only':True,'position':{a:i.get('base_pose',{}).get(a,0.) for a in ('x','y','z')},'size':{'x':.15,'y':.15,'z':.3}} for i in instances]
        robots=[{'instance':i,'model':{k:m[k] for k in ('robot','actuators','kinematics','capabilities','planning_supported') if k in m},'state':states[i['instance']['id']].model_dump(mode='json')} for i,m in zip(instances,models)]
        jobs=[public(json.loads(p.read_text())) for p in sorted(folder(pid).glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]]
        return {'cloud_session':os.getenv('ROBOT_IDE_DEPLOYMENT')=='cloud','project':{'id':pid,'name':project['name'],'description':project.get('description','')},'connected':connected,'backend':session.backend,'source':source,
            'objects':objects,'robots':robots,'assets':assets,'inventory_scope':inventory_scope,'observed_at':now(),'active_run':controller.leases.get(pid),
            'commands':jobs,'can_deploy_room':connected and bool(session.remote and session.remote.metadata.get('room_loading')),
            'scope':'Simulation only. Browser geometry is a simplified representation of the observed scene.'}

    @router.post('/projects/{pid}/stop')
    async def stop_workspace(pid:str):
        store.load_project(pid)
        run_id=controller.leases.get(pid)
        if not run_id:raise ValueError('No active run in this workspace')
        return controller.stop(run_id)

    @router.post('/projects/{pid}/connect')
    async def connect(pid:str):
        project=store.load_project(pid)[0]
        if project.get('simulation',{}).get('adapter')=='isaac_sim':await controller.gpu.ensure_running()
        controller.offline.pop(pid,None)
        await controller.context(pid)
        return {'connected':True}

    @router.get('/gpu')
    async def gpu_status():return await controller.gpu.snapshot()

    @router.post('/gpu/start',status_code=202)
    async def gpu_start():return controller.gpu.request_start()

    @router.get('/ai-models')
    async def ai_models():
        """Saved models a business user may pick per command, and the workspace defaults used otherwise."""
        from services.ai_orchestrator.two_stage import settings
        data=controller.llm.all();roles=settings(controller.llm)
        return {'models':[{'id':a['id'],'name':a['name'],'model':a['model']} for a in data['adapters']],
                'planner_adapter_id':roles.planner_adapter_id or data['default_id'],'task_adapter_id':roles.binding_adapter_id or data['default_id']}

    @router.post('/projects/{pid}/commands',status_code=201)
    async def prepare(pid:str,data:BusinessCommand):
        async with locks.setdefault(pid,asyncio.Lock()):
            cid=data.request_id.hex
            path=folder(pid)/(cid+'.json')
            if path.exists():
                job=read(pid,cid)
                if job['instruction']!=data.instruction.strip() or job.get('requested_robot')!=data.robot_id:raise HTTPException(409,'This request ID was already used for another command.')
                return public(job)
            controller.ensure_idle(pid)
            project,_,_,cell,_=await controller.context(pid)
            if any(cell.held_objects.values()):raise ValueError('An item is still held from an interrupted operation. Ask the workspace operator to release it or reset the simulator.')
            snapshot=await controller.snapshot(pid);stamp=fingerprint(snapshot)
            states=await controller.states(cell)
            aliases={}
            if cell.remote:
                try:aliases={a['planning_id']:a['name'] for a in (await cell.remote.inventory())['assets'] if a.get('planning_id')}
                except ValueError:pass
            if controller.llm.all()['default_id'] or data.planner_adapter_id:
                return await prepare_semantic(pid,data,cid,cell,states,snapshot,stamp)
            transfer=parse_transfer(data.instruction,cell.objects,aliases)
            candidates=[data.robot_id] if data.robot_id else list(cell.instances)
            if any(r not in cell.instances for r in candidates):raise ValueError('The selected robot is not in this workspace.')
            failures=[];revision=definition=None
            for rid in candidates:
                try:
                    model=cell.models[rid];instance=cell.instances[rid]
                    if transfer:
                        item,source,destination=transfer
                        tasks=transfer_tasks(model,instance,cell.objects,item,destination)
                    elif controller.llm.all()['default_id']:
                        from services.ai_orchestrator.task_drafting import draft_tasks
                        tasks=await draft_tasks(controller.llm,None,data.instruction,model,rid,cell.objects,states[rid].positions)
                    else:
                        intent=await get_provider(controller.llm).interpret(data.instruction,cell.objects)
                        tasks=expand_template(intent.template,model,instance,cell.objects,intent.object_id,intent.target_id)
                    definition=PlanDefinition(id=uuid.uuid4().hex[:12],project_id=pid,name=data.instruction.strip()[:120],goal=data.instruction.strip(),tasks=tasks)
                    revision=compile_definition(definition,cell.instances,cell.models,cell.objects,states,stamp,cell.backend)
                    if not revision.valid:raise ValueError('; '.join(c.message for c in revision.checks if c.status=='failed'))
                    validate_goal_outcome(data.instruction,cell.objects,revision)
                    break
                except ValueError as error:
                    failures.append(f'{instance["instance"]["name"] if rid in cell.instances else rid}: {error}')
                    revision=None
            if revision is None:raise ValueError('This command could not be planned. '+'; '.join(failures))
            controller.ensure_idle(pid)
            if fingerprint(await controller.snapshot(pid))!=stamp:raise HTTPException(409,'The workspace changed while preparing this command. Refresh and try again.')
            store.save_definition(definition);store.save_plan(revision,snapshot)
            job={'id':cid,'project_id':pid,'instruction':data.instruction.strip(),'requested_robot':data.robot_id,'definition_id':definition.id,'revision_id':revision.id,
                'fingerprint':revision.fingerprint,'backend':cell.backend,'robot_id':rid,'robot_name':cell.instances[rid]['instance']['name'],
                'status':'ready','duration':revision.duration,'created_at':now(),'run_id':None,'steps':[{'id':t.id,'name':t.name} for t in revision.atomic_tasks],
                'checks':[c.model_dump() for c in revision.checks]}
            save(pid,job)
            return public(job)

    @router.post('/projects/{pid}/commands/{cid}/run',status_code=202)
    async def run(pid:str,cid:str):
        async with locks.setdefault(pid,asyncio.Lock()):
            job=read(pid,cid)
            if job.get('run_id'):return public(job)
            if job['status']!='ready' or not job.get('revision_id'):raise ValueError('Resolve clarification, commands and validation before starting')
            try:run=await controller.execute_registered_plan(job['revision_id'],job['fingerprint'],pid,job['backend'])
            except ValueError as error:raise HTTPException(409,'The workspace is busy or changed. Prepare the command again. '+str(error)) from error
            job.update(status='running',run_id=run.id);save(pid,job)
            return public(job)

    @router.get('/projects/{pid}/commands/{cid}')
    async def command_status(pid:str,cid:str):return public(read(pid,cid))
    @router.post('/projects/{pid}/commands/{cid}/clarify')
    async def clarify(pid:str,cid:str,body:dict):
        async with locks.setdefault(pid,asyncio.Lock()):
            controller.ensure_idle(pid);job=read(pid,cid)
            if job['status']!='needs_clarification':raise ValueError('This command is not waiting for clarification')
            *_,cell,_=await controller.context(pid);snapshot=await controller.snapshot(pid)
            data=BusinessCommand(instruction=job['instruction'],request_id=uuid.UUID(hex=cid),robot_id=job.get('requested_robot'),image=body.get('image'))
            definition=store.get_definition(pid,job['definition_id'])
            return await prepare_semantic(pid,data,cid,cell,await controller.states(cell),snapshot,fingerprint(snapshot),body.get('answers',{}),definition)

    @router.post('/projects/{pid}/commands/{cid}/request-physical')
    async def request_physical(pid:str,cid:str):
        job=read(pid,cid)
        if not job.get('revision_id'):raise ValueError('Prepare and validate a revision first')
        plan=store.get_plan(pid,job['revision_id'])
        if not plan.validation_report or plan.validation_report.status!='passed':raise ValueError('Physical checking is incomplete or failed. Ask the IDE operator to resolve it first')
        record={'project_id':pid,'revision_id':plan.id,'business_command_id':cid,'status':'requested','requested_at':now(),'requested_by':'business'}
        atomic_json(store.runtime/'physical_approvals'/safe_id(pid)/(safe_id(plan.id)+'.json'),record)
        job['physical_status']='awaiting_ide_approval';save(pid,job);return public(job)

    @router.get('/projects/{pid}/commands/{cid}/run')
    async def progress(pid:str,cid:str):
        job=read(pid,cid)
        job=public(job)
        if not job.get('run_id'):raise ValueError('This command has not been started.')
        run=controller.runs.get(job['run_id']) or store.get_run(job['run_id'])
        if run.project_id!=pid:raise ValueError('Run belongs to another workspace.')
        return {k:v for k,v in run.model_dump(mode='json').items() if k in {'id','status','progress','elapsed','current_step','stop_requested','stopped_verified','finished_at','robot_states','frame','task_statuses','logs'}}

    @router.post('/projects/{pid}/commands/{cid}/stop')
    async def stop(pid:str,cid:str):
        job=read(pid,cid)
        if not job.get('run_id') and job.get('revision_id'):
            approval=store.runtime/'physical_approvals'/safe_id(pid)/(safe_id(job['revision_id'])+'.json')
            if approval.exists():job['run_id']=json.loads(approval.read_text()).get('run_id')
        if not job.get('run_id'):raise ValueError('No running execution for this command.')
        return controller.stop(job['run_id'])
    return router

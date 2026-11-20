"""Global setup, role configuration and two-stage project planning APIs."""
import json
import uuid
from pathlib import Path
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse
from pydantic import Field
from shared.models.domain import Contract,now,TaskDefinition
from shared.models.robotics import DriverDraft,RobotBinding,RoleSettings,SceneImage
from services.adapters.drivers import DriverRegistry,DriverProcess
from services.adapters.bindings import BindingRegistry,enrich_model
from services.api.storage import atomic_json,fingerprint,safe_id
from services.validation.registry import load_model,load_instance,validate_positions
from services.ai_orchestrator.two_stage import settings,save_settings,decompose,bind_tasks,catalog,task_signature,effective_models
from services.planning.motion_client import MotionClient


class GenerateDriver(Contract):
    name:str
    category:str
    sdk_version:str
    documentation:str=Field(min_length=1,max_length=60000)
    adapter_id:str|None=None


class ExpectedHash(Contract):
    expected_hash:str


class DecomposeRequest(Contract):
    version:int
    instruction:str=Field(min_length=1,max_length=4000)
    adapter_id:str|None=None
    clarifications:dict[str,str]=Field(default_factory=dict)
    image:SceneImage|None=None
    replace_tasks:bool=False


class BindRequest(Contract):
    version:int
    adapter_id:str|None=None


class SetupDraft(Contract):
    version:int=1
    stage:int=Field(default=0,ge=0,le=7)
    data:dict=Field(default_factory=dict)


class BindingTest(Contract):
    positions:dict[str,float]=Field(default_factory=dict)
    joint_id:str|None=None
    value:float|None=None


def robotics_router(store,controller,controls):
    router=APIRouter(prefix='/api')
    drivers=DriverRegistry(store,controller.llm);bindings=BindingRegistry(store,drivers)
    controller.drivers=drivers;controller.bindings=bindings;controller.motion=MotionClient(store)
    def idle():
        if controller.leases or controls.sessions:raise ValueError('Stop runs and close controls before changing global robot configuration')
    def current(pid,did,version):
        controller.ensure_idle(pid);d=store.get_definition(pid,did)
        if d.version!=version:raise HTTPException(409,'Plan changed; reload before editing')
        return d

    @router.get('/llm/roles')
    async def roles():return settings(controller.llm)
    @router.put('/llm/roles')
    async def set_roles(data:RoleSettings):idle();return save_settings(controller.llm,data)
    @router.get('/motion/configuration')
    async def motion_configuration():
        c=controller.motion.configuration();return {'url':c['url'],'token_set':(store.runtime/'connections/motion.token').exists(),'local_setup':getattr(controller,'motion_setup',{'status':'idle'})}
    @router.put('/motion/configuration')
    async def save_motion_configuration(body:dict):
        idle()
        from urllib.parse import urlsplit
        url=body['url'].rstrip('/');parsed=urlsplit(url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Choose a valid robotics worker URL without credentials or query parameters')
        atomic_json(store.runtime/'connections/motion.json',{'url':url,'token_env':'ROBOT_DE_MOTION_TOKEN','version':controller.motion.configuration().get('version',1)+1})
        if body.get('token'):
            if len(body['token'])<16:raise ValueError('Worker token must contain at least 16 characters')
            p=store.runtime/'connections/motion.token';p.write_text(body['token']);p.chmod(0o600)
        return {'saved':True,'requires_recompile':True}
    @router.post('/motion/start-local',status_code=202)
    async def start_motion():
        idle()
        import shutil,asyncio,sys,os
        from services.validation.registry import REPOSITORY_ROOT
        if not shutil.which('docker'):raise ValueError('Install Docker with a Linux engine; Windows uses WSL2. This action does not start cloud resources')
        if getattr(controller,'motion_job',None) and not controller.motion_job.done():return controller.motion_setup
        controller.motion_setup={'status':'building','message':'Building the local MoveIt/Nav2 image. This may take several minutes; no GCP VM is started.'}
        async def build():
            env={**os.environ,'PYTHONPATH':str(REPOSITORY_ROOT/'SERVER_CLIENT/server')+os.pathsep+str(REPOSITORY_ROOT)}
            log=store.runtime/'connections/motion-build.log';log.parent.mkdir(parents=True,exist_ok=True)
            try:
                with log.open('wb') as out:
                    for operation in ('build','start'):
                        process=await asyncio.create_subprocess_exec(sys.executable,str(REPOSITORY_ROOT/'scripts/robotics_worker.py'),operation,cwd=REPOSITORY_ROOT,env=env,stdout=out,stderr=out)
                        try:await asyncio.wait_for(process.wait(),1800)
                        except BaseException:process.kill();await process.wait();raise
                        if process.returncode:raise ValueError('Local worker setup failed. Check motion-build.log in the runtime connections folder')
                controller.motion_setup={'status':'ready','message':'Local robotics worker started; check its connection before testing MOVE.'}
            except BaseException as error:controller.motion_setup={'status':'failed','message':str(error)}
        controller.motion_job=asyncio.create_task(build());return controller.motion_setup
    @router.get('/motion/health')
    async def motion_health():return await controller.motion.health()
    @router.get('/library/driver-generations/failed')
    async def failed_generations():return [json.loads(p.read_text()) for p in sorted((store.runtime/'driver_generation_failures').glob('*.json'))]
    @router.post('/library/robot-bindings/suggest')
    async def suggest_mapping(body:dict):
        model=load_model(store.model_folder(body['model_id']));driver=drivers.get(body['driver_id'])
        from services.adapters.bindings import propose_mapping
        # Wheels are continuous in the URDF; the model stores them as revolute joints with a control window.
        continuous=[j['name'] for j in model.get('urdf_joint_metadata') or [] if j['type']=='continuous']
        result=await propose_mapping(controller.llm,body.get('adapter_id') or settings(controller.llm).binding_adapter_id,model['robot'],model['actuators']['actuators'],driver['definition'],continuous)
        return {**result,'reviewed':False}

    from services.imports.urdf import URDFImports,SuggestRequest
    from typing import Literal
    importer=URDFImports(store,controller.llm);auto_jobs={}
    class AutoSetup(Contract):
        draft_id:str=Field(min_length=1,max_length=40)
        documentation:str=Field(default='',max_length=60000)
        category:Literal['physical','virtual']='virtual'
        adapter_id:str|None=None
    @router.post('/library/auto-setup',status_code=202)
    async def auto_setup(data:AutoSetup):
        """Configure a robot from its URDF draft and documentation in one job: prefill, control adapter, mapping.

        Nothing is saved as a robot, reviewed or published here; the result is a proposal for the user to review."""
        import asyncio,re
        from services.adapters.drivers import IncompleteDriver
        idle()
        if data.category=='physical' and not data.documentation.strip():raise ValueError('A physical robot needs its vendor documentation to generate the control adapter')
        draft=importer.read(data.draft_id)
        roles=settings(controller.llm);adapter=data.adapter_id or roles.setup_adapter_id or roles.binding_adapter_id
        job={'id':uuid.uuid4().hex[:12],'status':'running','started_at':now(),'error':None,'result':None,
             'stages':{k:{'status':'pending','message':''} for k in ('prefill','adapter','mapping')}}
        auto_jobs[job['id']]=job;stages=job['stages']
        async def prefill():
            stages['prefill']['status']='running'
            result=await importer.autofill(data.draft_id,SuggestRequest(adapter_id=adapter,documentation=data.documentation))
            documented=sum(1 for p in result['provenance'].values() if p['source']=='documentation')
            stages['prefill'].update(status='done',message=f"{documented} values from the documentation, the rest from the URDF or marked defaults")
            return result
        async def control_adapter():
            if not data.documentation.strip():
                stages['adapter'].update(status='skipped',message='No documentation: a simulator adapter is made from the robot joints when you accept');return {'status':'simulator'}
            stages['adapter']['status']='running'
            version=re.search(r'\bversion\s+v?([0-9][\w.\-]*)',data.documentation,re.I)
            try:driver=await drivers.generate(f"{draft['parsed']['name']} adapter"[:120],data.category,version[1] if version else 'unspecified',data.documentation,adapter)
            except IncompleteDriver as error:
                stages['adapter'].update(status='needs_information',message=str(error)[:400])
                return {'status':'needs_information','draft':error.draft,'issues':error.issues,'failure_id':error.failure_id,'provenance':error.provenance}
            stages['adapter'].update(status='done',message=f"{len(driver['definition']['functions'])} control functions from the documentation")
            return {'status':'complete','driver':driver}
        job['request']={'draft_id':data.draft_id,'adapter_id':adapter}
        async def run():
            try:
                filled,generated=await asyncio.gather(prefill(),control_adapter())
                mapping=None
                if generated['status']=='complete':
                    stages['mapping']['status']='running'
                    mapping=await map_joints(draft,filled,generated['driver'],adapter)
                    mapped=sum(1 for j in mapping['joints'] if j['function_id'] or j['role']!='independent')
                    stages['mapping'].update(status='done',message=f"{mapped} of {len(mapping['joints'])} joints mapped")
                else:stages['mapping'].update(status='skipped',message='Mapped by joint name once the adapter exists')
                job.update(status='done',result={'prefill':filled,'adapter':generated,'mapping':mapping})
            except Exception as error:
                for stage in stages.values():
                    if stage['status'] in {'running','pending'}:stage.update(status='failed',message=str(error)[:400])
                job.update(status='failed',error=str(error)[:1000])
        job_task=asyncio.create_task(run());auto_jobs[job['id']+':task']=job_task
        return job
    async def map_joints(draft,filled,driver,adapter):
        from services.adapters.bindings import propose_mapping
        kinds={j['name']:j['type'] for j in draft['parsed']['joints']}
        actuators={jid:{'type':kinds[jid],'unit':'m' if kinds[jid]=='prismatic' else 'rad','min':v['min'],'max':v['max'],'velocity':v['velocity']}
                   for jid,v in filled['review']['joints'].items()}
        robot={'name':filled['review']['name'],'description':filled['review']['description']}
        return await propose_mapping(controller.llm,adapter,robot,actuators,driver['definition'],[j for j,k in kinds.items() if k=='continuous'])
    @router.post('/library/auto-setup/{job_id}/mapping')
    async def auto_setup_mapping(job_id:str,body:dict):
        """Propose the mapping again, for example after the AI model timed out on the first attempt."""
        job=auto_jobs.get(job_id) if ':' not in job_id else None
        if not job or job['status']!='done' or job['result']['adapter'].get('status')!='complete':raise ValueError('This setup has no generated adapter to map; start the setup again')
        adapter=body.get('adapter_id') or job['request']['adapter_id']
        mapping=await map_joints(importer.read(job['request']['draft_id']),job['result']['prefill'],job['result']['adapter']['driver'],adapter)
        job['result']['mapping']=mapping;mapped=sum(1 for j in mapping['joints'] if j['function_id'] or j['role']!='independent')
        job['stages']['mapping'].update(status='done',message=f"{mapped} of {len(mapping['joints'])} joints mapped")
        return mapping
    @router.get('/library/auto-setup/{job_id}')
    async def auto_setup_status(job_id:str):
        if job_id not in auto_jobs or ':' in job_id:raise HTTPException(404,'Setup job not found; start it again')
        return auto_jobs[job_id]

    @router.get('/library/drivers')
    async def list_drivers():return drivers.list()
    @router.post('/library/driver-templates/{template_id}',status_code=201)
    async def virtual_template(template_id:str):
        idle()
        from services.adapters.templates import template
        return drivers.save(template(template_id))
    @router.post('/library/drivers',status_code=201)
    async def create_driver(data:DriverDraft):idle();return drivers.save(data)
    @router.put('/library/drivers/{driver_id}')
    async def edit_driver(driver_id:str,data:DriverDraft):idle();return drivers.save(data,driver_id)
    @router.post('/library/drivers/simulator/{model_id}',status_code=201)
    async def simulator_driver(model_id:str):
        idle()
        from services.adapters.templates import simulator_for
        return drivers.save(simulator_for(load_model(store.model_folder(model_id))))
    @router.post('/library/drivers/generate-draft')
    async def generate_driver_draft(data:GenerateDriver):
        """Like /generate, but an incomplete answer returns an editable function table instead of failing."""
        idle()
        if data.category not in {'physical','virtual'}:raise ValueError('Select physical or virtual')
        from services.adapters.drivers import IncompleteDriver
        try:driver=await drivers.generate(data.name,data.category,data.sdk_version,data.documentation,data.adapter_id or settings(controller.llm).binding_adapter_id)
        except IncompleteDriver as error:return {'status':'needs_information','draft':error.draft,'issues':error.issues,'failure_id':error.failure_id,'provenance':error.provenance}
        return {'status':'complete','driver':driver,'issues':[],'provenance':driver.get('provenance')}
    @router.post('/library/drivers/generate',status_code=201)
    async def generate_driver(data:GenerateDriver):
        idle()
        if data.category not in {'physical','virtual'}:raise ValueError('Select physical or virtual')
        return await drivers.generate(data.name,data.category,data.sdk_version,data.documentation,data.adapter_id or settings(controller.llm).binding_adapter_id)
    @router.post('/library/drivers/{driver_id}/review')
    async def review_driver(driver_id:str,data:ExpectedHash):idle();return drivers.review(driver_id,data.expected_hash)
    @router.post('/library/drivers/{driver_id}/test')
    async def test_driver(driver_id:str):return await drivers.test(driver_id)

    @router.post('/library/manuals',status_code=201)
    async def upload_manual(request:Request,filename:str):
        idle();payload=bytearray()
        async for block in request.stream():
            payload.extend(block)
            if len(payload)>32*1024*1024:raise ValueError('Manual exceeds 32 MB')
        suffix=Path(filename).suffix.lower()
        if suffix=='.pdf':
            from pypdf import PdfReader
            import io
            reader=PdfReader(io.BytesIO(payload));pages=[{'page':n+1,'text':page.extract_text() or ''} for n,page in enumerate(reader.pages)]
            text='\n\n'.join(f"[Page {p['page']}]\n{p['text']}" for p in pages)
            if not text.strip() or not any(p['text'].strip() for p in pages):raise ValueError('Scanned PDF has no searchable text; supply OCR text or a searchable manual')
        elif suffix in {'.txt','.md','.json','.yaml','.yml'}:text=payload.decode('utf-8');pages=[{'page':1,'text':text}]
        else:raise ValueError('Upload searchable PDF, text, Markdown, JSON or YAML API definitions')
        if len(text)>60000:raise ValueError('Extracted manual exceeds the current 60,000-character context limit; upload the relevant actuator API section')
        mid=uuid.uuid4().hex[:12];atomic_json(store.runtime/'manuals'/mid/'document.json',{'id':mid,'filename':Path(filename).name,'text':text,'pages':pages,'sha256':__import__('hashlib').sha256(payload).hexdigest()})
        return {'id':mid,'text':text,'pages':len(pages)}

    @router.get('/library/setup-drafts')
    async def setup_drafts():return [json.loads(p.read_text()) for p in sorted((store.runtime/'setup_drafts').glob('*.json'))]
    @router.post('/library/setup-drafts',status_code=201)
    async def new_setup(data:SetupDraft):
        value={'id':uuid.uuid4().hex[:12],**data.model_dump(),'updated_at':now()};atomic_json(store.runtime/'setup_drafts'/(value['id']+'.json'),value);return value
    @router.put('/library/setup-drafts/{draft_id}')
    async def save_setup(draft_id:str,data:SetupDraft):
        path=store.runtime/'setup_drafts'/(safe_id(draft_id)+'.json');old=json.loads(path.read_text())
        if old['version']!=data.version:raise HTTPException(409,'Setup changed; reopen the draft')
        value={'id':draft_id,**data.model_dump(),'version':data.version+1,'updated_at':now()};atomic_json(path,value);return value

    @router.get('/library/robot-bindings')
    async def list_bindings():return bindings.list()
    @router.get('/library/models/{model_id}')
    async def setup_model(model_id:str):
        model=load_model(store.model_folder(model_id))
        model['initial_configuration']=load_instance(store.model_folder(model_id)/'instances/instance.yaml',model)['initial_configuration']
        return model
    @router.post('/library/robot-bindings',status_code=201)
    async def create_binding(data:RobotBinding):idle();return bindings.save(data)
    @router.put('/library/robot-bindings/{binding_id}')
    async def edit_binding(binding_id:str,data:RobotBinding):idle();return bindings.save(data,binding_id)
    @router.post('/library/robot-bindings/{binding_id}/test-actuators')
    async def test_mapping(binding_id:str,data:BindingTest):
        b=bindings.get(binding_id);d=drivers.get(b['definition']['driver_id']);model=load_model(store.model_folder(b['definition']['model_id']))
        initial=load_instance(store.model_folder(b['definition']['model_id'])/'instances/instance.yaml',model)['initial_configuration']['actuator_positions']
        q={**initial,**data.positions}
        mapping=b['definition']['joints'];functions={f['id']:f for f in d['definition']['functions']}
        selected=next((j for j in mapping if j['joint_id']==data.joint_id),None) if data.joint_id else None
        if data.joint_id and (not selected or selected['role']!='independent'):raise ValueError('Select an independent actuator to test')
        if data.joint_id and data.value is None:raise ValueError('Choose a joint test value')
        velocity=bool(selected and functions[selected['function_id']]['mode']=='velocity')
        if selected and not velocity:q[data.joint_id]=data.value
        if velocity and abs(data.value)>model['actuators']['actuators'][data.joint_id]['velocity']:raise ValueError('Wheel test speed exceeds the configured angular velocity limit')
        validate_positions(model,q);process=DriverProcess()
        commands=[{'function':j['function_id'],'value':((data.value if velocity and selected==j else 0.)*j['scale'] if functions[j['function_id']]['mode']=='velocity' else q[j['joint_id']]*j['scale']+j['offset'])} for j in mapping if j['role']=='independent' and (not data.joint_id or j['joint_id']==data.joint_id)]
        initial_values={j['function_id']:(initial[j['joint_id']]*j['scale']+j['offset'] if functions[j['function_id']]['mode']=='position' else 0.) for j in mapping if j['role']=='independent'}
        try:
            await process.start(d,initial_values=initial_values);result=await process.request({'operation':'command','commands':commands})
            for j in mapping:
                if j['function_id'] in result.get('observed_values',{}):
                    if functions[j['function_id']]['mode']=='position':q[j['joint_id']]=(result['observed_values'][j['function_id']]-j['offset'])/j['scale']
                    elif selected==j:q[j['joint_id']]+=result['observed_values'][j['function_id']]/j['scale']*.2
            for _ in mapping:
                for j in mapping:
                    if j['role']=='coupled':q[j['joint_id']]=q[j['coupled_to']]*j['multiplier']+j['offset']
            validate_positions(model,q)
            tested=set(b['test_evidence'].get('actuators',{}).get('tested_joints',[]))
            tested.update(j['joint_id'] for j in mapping if j['function_id'] in {c['function'] for c in commands})
            await process.request({'operation':'stop'})
            return bindings.record_test(binding_id,'actuators',{'passed':True,'tested_joints':sorted(tested),'source':'simulation','positions':q,'sdk_calls':result.get('sdk_calls',[]),'hardware_contacted':False})
        finally:await process.close()
    @router.post('/library/robot-bindings/{binding_id}/test-move')
    async def test_move(binding_id:str,body:dict):
        b=bindings.get(binding_id);model=enrich_model(load_model(store.model_folder(b['definition']['model_id'])),b)
        initial=load_instance(store.model_folder(b['definition']['model_id'])/'instances/instance.yaml',model)['initial_configuration']['actuator_positions']
        from services.ai_orchestrator.two_stage import normalize_call
        from shared.models.robotics import FunctionCall
        goal=normalize_call(FunctionCall(function='MOVE',arguments=body),model)
        from services.planning.motion_client import MotionUnavailable
        from services.planning.compiler_v2 import preview_goal
        from shared.models.domain import Frame
        from services.validation.trajectory import validate_trajectory
        base={'x':0,'y':0,'z':0,'yaw':0}
        try:plan=await controller.motion.plan(model,initial,base,goal,[])
        except MotionUnavailable:plan={'samples':preview_goal(model,initial,base,goal),'engine':'portable_kinematic_preview'}
        path=plan.get('samples',[])
        if not 2<=len(path)<=5000:raise ValueError('Choose a bounded MOVE test with 2–5000 samples')
        validate_trajectory(model,[Frame(time=s['time'],step_id='move_test',positions=s['positions'],objects={}) for s in path],[],check_geometry=model.get('mobility',{}).get('classification','STATIONARY')=='STATIONARY')
        d=drivers.get(b['definition']['driver_id']);functions={f['id']:f for f in d['definition']['functions']};mapping=b['definition']['joints'];process=DriverProcess()
        initial_values={j['function_id']:initial[j['joint_id']]*j['scale']+j['offset'] if functions[j['function_id']]['mode']=='position' else 0. for j in mapping if j['role']=='independent'}
        try:
            await process.start(d,initial_values=initial_values);previous=path[0];writes=0
            for sample in path:
                dt=sample['time']-previous['time'];commands=[]
                for j in mapping:
                    if j['role']!='independent':continue
                    f=functions[j['function_id']];value=sample['positions'][j['joint_id']]*j['scale']+j['offset'] if f['mode']=='position' else (sample['positions'][j['joint_id']]-previous['positions'][j['joint_id']])/dt*j['scale'] if dt else 0.
                    commands.append({'function':f['id'],'value':value})
                result=await process.request({'operation':'command','commands':commands});writes+=len(result.get('sdk_calls',[]));previous=sample
            await process.request({'operation':'stop'})
            return bindings.record_test(binding_id,'move',{'passed':True,'engine':plan.get('engine'),'source':'simulation','samples':path,'generated_sdk_writes':writes,'hardware_contacted':False,'hardware_validated':False})
        finally:await process.close()
    @router.post('/library/robot-bindings/{binding_id}/review')
    async def review_binding(binding_id:str,data:ExpectedHash):idle();return bindings.review(binding_id,data.expected_hash)
    @router.post('/library/robot-bindings/{binding_id}/publish')
    async def publish_binding(binding_id:str):idle();return bindings.publish(binding_id)

    @router.post('/projects/{pid}/robots/{rid}/mapped-preview')
    async def mapped_preview(pid:str,rid:str,body:dict):
        controller.ensure_idle(pid)
        *_,cell,_=await controller.context(pid,rid);model=cell.models[rid];binding=model.get('binding')
        if not binding or not binding['published']:raise ValueError('Choose a published mapping first')
        q=body['positions'];base=body['base'];validate_positions(model,q);controls.check_base(base)
        from shared.models.robotics import FunctionCall
        from services.ai_orchestrator.two_stage import normalize_call
        from services.planning.compiler_v2 import preview_goal
        from services.planning.motion_client import MotionUnavailable
        from services.validation.trajectory import validate_trajectory
        from shared.models.domain import Frame
        goal=normalize_call(FunctionCall.model_validate(body['call']),model)
        if goal['kind'] not in {'joint','tool','base'}:raise ValueError('Preview supports position, component and deterministic MOVE commands; use bounded base MOVE for wheels')
        try:planned=await controller.motion.plan(model,q,base,goal,cell.objects);path=planned['samples']
        except MotionUnavailable:path=preview_goal(model,q,base,goal)
        if not path:raise ValueError('No preview trajectory returned')
        validate_trajectory(model,[Frame(time=s['time'],step_id='preview',positions=s['positions'],objects={}) for s in path],cell.objects,check_geometry=model.get('mobility',{}).get('classification','STATIONARY')=='STATIONARY')
        target=dict(path[-1]['positions']);driver=drivers.get(binding['definition']['driver_id']);mapping=binding['definition']['joints']
        functions={f['id']:f for f in driver['definition']['functions']}
        initial={j['function_id']:(q[j['joint_id']]*j['scale']+j['offset'] if functions[j['function_id']]['mode']=='position' else 0.) for j in mapping if j['role']=='independent'}
        commands=[{'function':j['function_id'],'value':target[j['joint_id']]*j['scale']+j['offset'] if functions[j['function_id']]['mode']=='position' else 0.} for j in mapping if j['role']=='independent' and (goal['kind']!='joint' or j['joint_id']==goal['joint'])]
        process=DriverProcess()
        try:
            await process.start(driver,initial_values=initial);result=await process.request({'operation':'command','commands':commands});await process.request({'operation':'stop'})
            for j in mapping:
                if j['role']=='independent' and functions[j['function_id']]['mode']=='position':target[j['joint_id']]=(result['observed_values'][j['function_id']]-j['offset'])/j['scale']
            for _ in mapping:
                for j in mapping:
                    if j['role']=='coupled':target[j['joint_id']]=target[j['coupled_to']]*j['multiplier']+j['offset']
            validate_positions(model,target);controller.ensure_idle(pid)
            return {'positions':target,'base':path[-1]['base_pose'],'source':'simulation','hardware_contacted':False,'sdk_calls':result.get('sdk_calls',[])}
        finally:await process.close()

    @router.get('/projects/{pid}/robots/{rid}/functions')
    async def robot_functions(pid:str,rid:str):
        *_,cell,_=await controller.context(pid,rid);return catalog(cell.models[rid])
    @router.put('/projects/{pid}/robots/{rid}/binding')
    async def assign_binding(pid:str,rid:str,body:dict):
        controller.ensure_idle(pid)
        if controls.sessions:raise ValueError('Close manual controls before changing project bindings')
        b=bindings.get(body['binding_id'])
        if not b['published']:raise ValueError('Publish the reviewed and tested binding first')
        d=drivers.get(b['definition']['driver_id']);project,instances,_,_=store.load_project(pid)
        index=next((i for i,x in enumerate(instances) if x['instance']['id']==rid),None)
        if index is None or instances[index]['robot_model']['id']!=b['definition']['model_id']:raise ValueError('Binding does not match the project robot')
        instance=instances[index];instance['control_adapter']={'adapter_id':d['id'],'category':d['definition']['category'],'adapter_hash':d['hash'],'binding_id':b['id'],'binding_hash':b['hash']}
        import yaml
        path=store.project_folder(pid)/project['robots'][index];tmp=path.with_suffix('.binding.tmp');tmp.write_text(yaml.safe_dump(instance));tmp.replace(path)
        if pid in controller.sessions:
            controller.sessions[pid].instances[rid]=instance
            controller.sessions[pid].models[rid]=enrich_model(controller.sessions[pid].models[rid],b)
        return {'instance':instance,'requires_recompile':True,'hardware_authorized':False}

    @router.get('/projects/{pid}/plan-definitions/{did}/effective-models')
    async def plan_models(pid:str,did:str):return effective_models(controller.llm,store.get_definition(pid,did))
    @router.post('/projects/{pid}/plan-definitions/{did}/decompose')
    async def decompose_plan(pid:str,did:str,data:DecomposeRequest):
        definition=current(pid,did,data.version)
        if definition.tasks and not data.replace_tasks:raise ValueError('Existing tasks are preserved. Explicitly confirm replacement before regenerating this plan')
        candidate=definition.model_copy(deep=True);candidate.goal=data.instruction
        *_,cell,_=await controller.context(pid);states=await controller.states(cell);stamp=fingerprint(await controller.snapshot(pid))
        proposal=await decompose(controller.llm,candidate,cell,states,stamp,data.clarifications,data.image,data.adapter_id)
        if fingerprint(await controller.snapshot(pid))!=stamp:raise HTTPException(409,'Scene changed while planning; capture and plan again')
        definition=current(pid,did,data.version);definition.goal=data.instruction
        definition.planning_status='tasks_ready' if proposal.status=='ready' else proposal.status
        definition.clarification_questions=proposal.questions;definition.planning_error=proposal.error;definition.scene_snapshot_id=stamp
        definition.inference_evidence=candidate.inference_evidence
        if proposal.status=='ready':definition.tasks=proposal.tasks
        definition.version+=1;definition.updated_at=now();store.save_definition(definition);return definition
    @router.post('/projects/{pid}/plan-definitions/{did}/bind-commands')
    async def bind_commands(pid:str,did:str,data:BindRequest):
        definition=current(pid,did,data.version)
        if definition.planning_status in {'needs_clarification','unsupported'}:raise ValueError('Resolve the planner questions before binding commands')
        *_,cell,_=await controller.context(pid);stamp=fingerprint(await controller.snapshot(pid))
        errors=await bind_tasks(controller.llm,definition,cell,cell.objects,data.adapter_id)
        if fingerprint(await controller.snapshot(pid))!=stamp:raise HTTPException(409,'Scene changed while binding; resolve against the current scene')
        current(pid,did,data.version)
        definition.planning_status='tasks_ready' if errors else 'commands_ready';definition.version+=1;definition.updated_at=now();store.save_definition(definition)
        return {'definition':definition,'errors':errors}
    @router.put('/projects/{pid}/plan-definitions/{did}/roles')
    async def plan_roles(pid:str,did:str,data:RoleSettings):
        controller.ensure_idle(pid);definition=store.get_definition(pid,did)
        definition.role_settings=data;definition.version+=1;store.save_definition(definition);return definition

    @router.get('/registry/{model_id}/source/assets/{digest}')
    async def robot_asset(model_id:str,digest:str):
        folder=store.model_folder(model_id)/'source';metadata=json.loads((folder/'import.json').read_text())
        item=next((m for m in metadata['meshes'] if m.get('sha256')==digest and m.get('status')=='retained'),None)
        if not item:raise FileNotFoundError('Robot mesh unavailable')
        path=(folder/'package'/item['path']).resolve()
        if not path.is_relative_to((folder/'package').resolve()):raise ValueError('Invalid robot mesh path')
        import hashlib
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Robot mesh changed; reimport and review it')
        return FileResponse(path)
    return router

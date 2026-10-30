"""V2 contracts: real generated subprocesses, review gates and typed planning."""
import base64
import copy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.api.storage import fingerprint
from services.adapters.drivers import DriverRegistry, DriverProcess
from services.ai_orchestrator.two_stage import bind_tasks, decompose, task_signature, validate_image
from services.execution.controller import SimulationController
from services.planning.compiler_v2 import compile_v2
from services.planning.motion_client import MotionUnavailable
from shared.models.domain import PlanDefinition, TaskDefinition
from shared.models.robotics import DriverDraft, FunctionCall, SceneImage


def driver_data(**changes):
    value={'name':'Documented two-joint SDK','category':'physical','sdk_version':'1.0',
        'documentation':'set_joints(values) writes a joint dictionary. Shoulder range -1.0 to 1.0; elbow range -2.0 to 2.0. read_joints() returns joint values. halt() stops. close() disconnects.',
        'functions':[{'id':'shoulder','vendor_method':'set_joints','minimum':-1.,'maximum':1.,'unit':'rad','write_style':'joint_vector','vendor_joint':'j1','documentation_quote':'set_joints(values) writes a joint dictionary. Shoulder range -1.0 to 1.0; elbow range -2.0 to 2.0.'},
                     {'id':'elbow','vendor_method':'set_joints','minimum':-2.,'maximum':2.,'unit':'rad','write_style':'joint_vector','vendor_joint':'j2','documentation_quote':'set_joints(values) writes a joint dictionary. Shoulder range -1.0 to 1.0; elbow range -2.0 to 2.0.'}],
        'feedback_method':'read_joints','stop_method':'halt','disconnect_method':'close'}
    value.update(changes)
    return DriverDraft.model_validate(value)


async def test_generated_driver_exercises_actual_code_and_preserves_peers(store):
    registry=DriverRegistry(store,None);bundle=registry.save(driver_data())
    tested=await registry.test(bundle['id'])
    assert tested['test_report']['passed'] and not tested['test_report']['hardware_validated']
    process=DriverProcess()
    try:
        await process.start(bundle,initial_values={'shoulder':.2,'elbow':-.8})
        result=await process.request({'operation':'command','commands':[{'function':'shoulder','value':.6}]})
        assert result['observed_values']=={'shoulder':.6,'elbow':-.8}
        assert result['sdk_calls']==[{'method':'set_joints','value':{'j1':.6,'j2':-.8}}]
        before=await process.request({'operation':'trace'})
        for commands in ([{'function':'shoulder','value':0},{'function':'missing','value':0}], [{'function':'elbow','value':10}]):
            with pytest.raises(ValueError):await process.request({'operation':'command','commands':commands})
        assert before==await process.request({'operation':'trace'})
    finally:await process.close()
    assert process.process.returncode is not None


async def test_driver_tests_reject_wrong_edit_and_never_import_vendor(store):
    registry=DriverRegistry(store,None)
    bundle=registry.save(driver_data(sdk_module='module_that_must_never_be_imported'))
    assert (await registry.test(bundle['id']))['test_report']['passed']
    bad=driver_data(source_code=bundle['source_code'].replace('[\'j1\'] = value','[\'j2\'] = value'))
    draft=registry.save(bad)
    with pytest.raises(ValueError,match='wrong actuator|another actuator'):
        await registry.test(draft['id'])
    with pytest.raises(ValueError,match='exact documentation'):
        registry.save(driver_data(functions=[{**driver_data().functions[0].model_dump(),'vendor_method':'invented'}]))
    with pytest.raises(ValueError,match='bounded'):
        registry.save(driver_data(source_code='import socket\n'))


async def test_driver_edit_clears_all_qualification(store):
    registry=DriverRegistry(store,None);b=registry.save(driver_data())
    registry.review(b['id'],b['hash']);await registry.test(b['id'])
    edited=registry.save(driver_data(name='New SDK revision'),b['id'])
    assert edited['version']==2 and edited['hash']!=b['hash']
    assert edited['reviewed_hash'] is None and edited['test_report'] is None and not edited['hardware_validations']


class AnswerRegistry:
    def __init__(self,folder,answers):self.folder=folder;self.answers=iter(answers);self.calls=[]
    def resolve(self,selected=None):return {'id':'test','supports_vision':False}
    def adapter(self,selected=None,**options):
        async def invoke(input,system,**kwargs):
            self.calls.append((selected,input,system,kwargs))
            return {'answer':next(self.answers),'adapter_id':'test','adapter_version':1,'model':'test-model',
                    'provider_host':'llm.test','duration_seconds':0.1,'usage':{'total_tokens':5},'finish_reason':'stop'}
        return invoke


async def test_two_stages_manual_binding_and_clarification(store):
    import json
    runtime=SimulationController(store)
    try:
        *_,cell,_=await runtime.context('apple_transfer');states=await runtime.states(cell)
        task=TaskDefinition(id='point',name='Point shoulder',intent='Move shoulder to 0.3 radians',operation='command',robot_id='arm_01',binding_status='unresolved')
        definition=PlanDefinition(id='two_stage',project_id='apple_transfer',name='Point',goal='Point shoulder',tasks=[])
        registry=AnswerRegistry(store.runtime/'llm',[json.dumps({'status':'ready','tasks':[task.model_dump()]}),json.dumps({'calls':[{'function':'set_shoulder','arguments':{'value':.3,'unit':'rad'}}]})])
        proposal=await decompose(registry,definition,cell,states,'snapshot')
        assert proposal.tasks[0].function_calls==[] and proposal.tasks[0].binding_status=='unresolved'
        definition.tasks=proposal.tasks
        assert not await bind_tasks(registry,definition,cell,cell.objects)
        assert definition.tasks[0].binding_status=='resolved'
        assert len(registry.calls)==2 and 'PLANNER' in registry.calls[0][2] and 'ACTUATOR COMMAND CONVERTER' in registry.calls[1][2]
        assert [(e.stage,e.task_id,e.model,e.provider_host) for e in definition.inference_evidence]==[('planner',None,'test-model','llm.test'),('binder','point','test-model','llm.test')]
        # Hand-authored calls do not invoke the LLM again.
        definition.tasks[0].authored_by='user';definition.tasks[0].function_calls=[FunctionCall(function='set_shoulder',arguments={'value':.2,'unit':'rad'})]
        assert not await bind_tasks(registry,definition,cell,cell.objects)
        assert len(registry.calls)==2
        registry=AnswerRegistry(store.runtime/'llm',[json.dumps({'status':'needs_clarification','questions':['How long should arm one wave?']})])
        assert (await decompose(registry,definition,cell,states,'snapshot')).questions
    finally:await runtime.close()


async def test_invalid_calls_remain_visible_and_velocity_requires_duration(store):
    import json
    runtime=SimulationController(store)
    try:
        *_,cell,_=await runtime.context('apple_transfer')
        definition=PlanDefinition(id='bad_call',project_id='apple_transfer',name='Bad',tasks=[TaskDefinition(id='bad',name='Invented',operation='command',robot_id='arm_01',binding_status='unresolved')])
        registry=AnswerRegistry(store.runtime/'llm',[json.dumps({'calls':[{'function':'fly','arguments':{}}]})])
        errors=await bind_tasks(registry,definition,cell,cell.objects)
        assert errors[0]['task_id']=='bad' and definition.tasks[0].binding_status=='unresolved'
        assert 'not available' in definition.tasks[0].binding_error
    finally:await runtime.close()


async def test_vlm_missing_provider_and_stale_image_block(store):
    from services.api.storage import atomic_json
    runtime=SimulationController(store)
    try:
        *_,cell,_=await runtime.context('apple_transfer')
        registry=AnswerRegistry(store.runtime/'llm',[])
        atomic_json(registry.folder/'roles.json',{'vision_enabled':True})
        definition=PlanDefinition(id='vision',project_id='apple_transfer',name='Vision')
        with pytest.raises(ValueError,match='fresh scene image'):await decompose(registry,definition,cell,await runtime.states(cell),'snapshot')
        image=SceneImage(snapshot_id='snapshot',captured_at=datetime.now(timezone.utc).isoformat(),mime_type='image/png',data_base64=base64.b64encode(b'\x89PNG\r\n\x1a\n').decode())
        with pytest.raises(ValueError,match='vision-capable'):await decompose(registry,definition,cell,await runtime.states(cell),'snapshot',image=image)
        image.captured_at=(datetime.now(timezone.utc)-timedelta(seconds=40)).isoformat()
        with pytest.raises(ValueError,match='stale'):validate_image(image,'snapshot')
        assert not registry.calls
    finally:await runtime.close()


async def test_typed_compile_reports_incomplete_without_linux_worker(store):
    class Absent:
        async def plan(self,*args):raise MotionUnavailable('not started')
        async def validate(self,*args):raise MotionUnavailable('not started')
    runtime=SimulationController(store)
    try:
        *_,cell,_=await runtime.context('apple_transfer');states=await runtime.states(cell)
        task=TaskDefinition(id='shoulder',name='Raise shoulder',operation='command',robot_id='arm_01',binding_status='resolved',function_calls=[FunctionCall(function='set_shoulder',arguments={'value':states['arm_01'].positions['shoulder']+.04,'unit':'rad'})])
        task.binding_fingerprint=task_signature(task,cell.models['arm_01'])
        definition=PlanDefinition(id='typed',project_id='apple_transfer',name='Typed',tasks=[task])
        revision=await compile_v2(store,definition,cell,states,'stamp',Absent())
        assert revision.valid,revision.checks
        assert revision.validation_report.status=='incomplete' and not revision.validation_report.hardware_validated
        assert revision.frames[-1].robot_positions['arm_01']['shoulder']==pytest.approx(task.function_calls[0].arguments['value'])
        task.intent='Edited objective'
        with pytest.raises(ValueError,match='stale'):await compile_v2(store,definition,cell,states,'stamp',Absent())
    finally:await runtime.close()


def test_dependency_deletion_requires_repair_and_migration_is_repeatable(store):
    with TestClient(create_app(store)) as client:
        p=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'Dependency test'}).json();url='/api/projects/apple_transfer/plan-definitions/'+p['id']
        a=TaskDefinition(id='a',name='First',operation='move',robot_id='arm_01');b=a.model_copy(update={'id':'b','dependencies':['a']})
        p=client.put(url,json={**{k:p[k] for k in ('version','name','goal')},'tasks':[a.model_dump(),b.model_dump()]}).json()
        response=client.put(url,json={**{k:p[k] for k in ('version','name','goal')},'tasks':[b.model_dump()]})
        assert response.status_code==422 and 'Repair dependent' in response.text
        folder=store.project_folder('apple_transfer')/'plans'/p['id'];path=folder/'definition.json'
        legacy=path.read_text();value=__import__('json').loads(legacy);value.pop('schema_version');path.write_text(__import__('json').dumps(value))
        before=path.read_text();first=store.get_definition('apple_transfer',p['id']);second=store.get_definition('apple_transfer',p['id'])
        assert first==second and first.schema_version==2
        assert (store.project_folder('apple_transfer')/'migration_backups/v2'/p['id']/'definition.json').read_text()==before


def test_template_publish_explicit_pairing_and_simulated_generated_dispatch(store):
    from services.planning.kinematics import forward
    with TestClient(create_app(store,speed=500)) as client:
        driver=client.post('/api/library/driver-templates/stationary_arm').json()
        assert driver['definition']['category']=='virtual'
        assert client.post(f"/api/library/drivers/{driver['id']}/review",json={'expected_hash':driver['hash']}).status_code==200
        tested=client.post(f"/api/library/drivers/{driver['id']}/test");assert tested.status_code==200,tested.text
        model=client.get('/api/library/models/demo_arm').json();initial=model['initial_configuration']['actuator_positions']
        binding=client.post('/api/library/robot-bindings',json={'model_id':'demo_arm','driver_id':driver['id'],'joints':[{'joint_id':j,'function_id':'set_'+j,'alias':j} for j in initial],'end_effectors':{'parallel_gripper':{'link':'tool','xyz':[0,0,0],'rpy':[0,0,0]}}}).json()
        route='/api/library/robot-bindings/'+binding['id']
        assert client.post(route+'/publish').status_code==422
        for joint,value in initial.items():
            result=client.post(route+'/test-actuators',json={'joint_id':joint,'value':value});assert result.status_code==200,result.text
        point=forward(model,initial)
        moved=client.post(route+'/test-move',json={'target':'parallel_gripper','position':[point.x,point.y,point.z],'frame':'world'})
        assert moved.status_code==200,moved.text
        assert moved.json()['test_evidence']['move']['generated_sdk_writes']>0
        assert client.post(route+'/review',json={'expected_hash':binding['hash']}).status_code==200
        assert client.post(route+'/publish').json()['published']
        assert client.put('/api/projects/apple_transfer/robots/arm_01/binding',json={'binding_id':binding['id']}).status_code==200
        definition=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'Through generated SDK','goal':'Set the base yaw to 0.02 rad'}).json();url='/api/projects/apple_transfer/plan-definitions/'+definition['id']
        task=TaskDefinition(id='turn',name='Turn',operation='command',robot_id='arm_01',binding_status='unresolved',authored_by='user',function_calls=[FunctionCall(function='set_base_yaw',arguments={'value':.02,'unit':'rad'})])
        edited=client.put(url,json={**{k:definition[k] for k in ('name','goal','version')},'tasks':[task.model_dump()]}).json()
        bound=client.post(url+'/bind-commands',json={'version':edited['version']});assert bound.status_code==200,bound.text
        compiled=client.post(url+'/compile');assert compiled.status_code==201,compiled.text
        revision=compiled.json();assert revision['valid'],revision['checks']
        started=client.post(f"/api/projects/apple_transfer/plans/{revision['id']}/simulate",json={'fingerprint':revision['fingerprint']});assert started.status_code==202,started.text
        import time
        rid=started.json()['id']
        for _ in range(100):
            run=client.get('/api/runs/'+rid).json()
            if run['finished_at']:break
            time.sleep(.01)
        assert run['status']=='SIMULATION_PASSED',run['logs']
        assert run['evidence']['generated_driver_dispatch']['hardware_contacted'] is False
        # A changed global driver leaves the project inspectable and repairable,
        # but does not reuse its old approval or motion revision.
        changed=client.put('/api/library/drivers/'+driver['id'],json={**driver['definition'],'name':'Updated SDK'});assert changed.status_code==200
        detail=client.get('/api/projects/apple_transfer');assert detail.status_code==200,detail.text
        assert detail.json()['robots'][0]['model']['binding_stale']
        rejected=client.post(url+'/compile');assert rejected.status_code==422 and 'mapping changed' in rejected.text.lower()
        from services.adapters.drivers import DriverRegistry
        assert DriverRegistry(store,None).get_revision(driver['id'],driver['hash'])['source_code']==driver['source_code']


def test_missing_documented_numeric_limits_are_rejected(store):
    data=driver_data();data.functions[0].maximum=50
    with pytest.raises(ValueError,match='numeric limits'):DriverRegistry(store,None).save(data)


def test_observed_grasp_requires_following_motion_and_clears_on_slip_or_release():
    from simulation.isaac_sim.grasp_feedback import ObservedGrasp
    tracker=ObservedGrasp();item=lambda z:[{'id':'apple','position':[0.,0.,z]}]
    for n in range(10):assert tracker.update('arm',[0,0,.1],item(.1),True,n*.04) is None
    assert tracker.update('arm',[0,0,.106],item(.106),True,.4) is None
    assert tracker.update('arm',[0,0,.115],item(.115),True,.44)=='apple'
    assert tracker.update('arm',[0,0,.14],item(.115),True,.48) is None
    for n in range(5):tracker.update('arm',[0,0,.1+n*.004],item(.1+n*.004),True,1+n*.04)
    assert tracker.update('arm',[0,0,.12],item(.12),False,1.3) is None


def test_isaac_robot_transfer_is_pinned_declarative_and_does_not_overwrite(store,tmp_path):
    from services.api.storage import Storage
    from services.validation.registry import load_model
    from simulation.isaac_sim.robot_packages import package_model,receive_package
    model=load_model(store.model_folder('demo_arm'));package=package_model(store,model)
    assert all(not p.endswith('.py') for p in package['files'])
    target=Storage(tmp_path/'receiver')
    assert receive_package(target,package)=='demo_arm'
    tampered=copy.deepcopy(package);tampered['files']['robot.yaml']='YQ=='
    with pytest.raises(ValueError,match='checksum'):receive_package(target,tampered)
    dangerous=copy.deepcopy(package);dangerous['files']['source/driver.py']=base64.b64encode(b'import socket').decode()
    dangerous['hash']=fingerprint({k:dangerous[k] for k in ('files','model_id')})
    with pytest.raises(ValueError,match='declarative'):receive_package(target,dangerous)
    escape=copy.deepcopy(package);escape['files']['../outside.yaml']='YQ=='
    escape['hash']=fingerprint({k:escape[k] for k in ('files','model_id')})
    with pytest.raises(ValueError,match='declarative'):receive_package(target,escape)
    assert load_model(target.model_folder('demo_arm'))==model

@pytest.mark.parametrize('filename,classification,template_id,tool',[('bench_gantry.urdf','STATIONARY','gantry','tool_tip'),('differential_rover.urdf','MOVING','differential_drive','base_link'),('mobile_manipulator.urdf','BOTH','mobile_manipulator','tool_tip')])
def test_import_and_map_all_supported_robot_classes(store,filename,classification,template_id,tool):
    from services.imports.urdf import URDFImports,Review
    from services.api.model_library import ModelBundle,register_bundle
    from services.ai_orchestrator.llm import LLMRegistry
    from services.adapters.templates import template
    from services.adapters.bindings import BindingRegistry
    from shared.models.robotics import RobotBinding
    from services.validation.registry import ROOT
    imports=URDFImports(store,LLMRegistry(store));draft=imports.create((ROOT/'examples/robots'/filename).read_bytes(),filename)
    joints={j['name']:{'min':j['min'] if j['min'] is not None else -1000.,'max':j['max'] if j['max'] is not None else 1000.,'velocity':j['velocity'],'acceleration':20. if j['type']=='continuous' else .8,'initial':0.} for j in draft['parsed']['joints'] if j['type']!='fixed'}
    review=Review(id='fixture_'+classification.lower(),name='Fixture '+classification,tool_link=tool,joints=joints,reviewed=True)
    bundle,provenance=imports.build(draft['id'],review);model=register_bundle(store,ModelBundle.model_validate(bundle),source=(imports.folder(draft['id']),provenance))
    drivers=DriverRegistry(store,None);driver=drivers.save(template(template_id))
    mobility={'classification':classification,'priority':'arm_first'}
    if classification!='STATIONARY':mobility.update(left_wheel='left_wheel',right_wheel='right_wheel',wheel_radius_m=.05,track_width_m=.3,footprint=[[-.17,-.17],[.17,-.17],[.17,.17],[-.17,.17]],navigation_bounds=[-2,-2,2,2],transit_positions={k:0. for k in joints})
    data=RobotBinding(model_id=model['robot']['id'],driver_id=driver['id'],joints=[{'joint_id':key,'alias':key.replace('_',' '),'function_id':'set_'+key} for key in joints],mobility=mobility,end_effectors={} if classification=='MOVING' else {'tool':{'link':tool,'xyz':[0,0,0],'rpy':[0,0,0]}},reviewed=True)
    binding=BindingRegistry(store,drivers).save(data)
    assert binding['definition']['mobility']['classification']==classification
    assert len(binding['definition']['joints'])==len(joints)
    assert not binding['published'] and not binding['hardware_validations']

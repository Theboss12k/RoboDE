"""Backend support for the Simple/Expert IDE: model discovery, effective models and recoverable generation."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.ai_orchestrator.llm import LLMRegistry, ProviderConfiguration, connection_type
from services.execution.controller import SimulationController
from shared.models.domain import PlanDefinition, TaskDefinition


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    for key in ('AI_BASE_URL','AI_MODEL','AI_API_KEY'):
        monkeypatch.delenv(key,raising=False)


def fake_backend(monkeypatch,handler):
    original=httpx.AsyncClient
    monkeypatch.setattr('services.ai_orchestrator.llm.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


def profile(**kw):
    return ProviderConfiguration(**{'name':'Bolt','base_url':'http://gpu.local:11434/v1','model':'nemotron-3.5-bolt:e4b-q4_K_M',**kw})


def test_connection_types_are_inferred_for_existing_profiles():
    assert connection_type({'base_url':'http://127.0.0.1:11434/v1'})=='ollama'
    assert connection_type({'base_url':'https://api.tokenfactory.nebius.com/v1'})=='openai'
    assert connection_type({'protocol':'python_function','base_url':'http://x'})=='custom'
    assert connection_type({'connection_type':'openai','base_url':'http://127.0.0.1:11434/v1'})=='openai'


def test_discovery_lists_models_read_only_and_status_keeps_unavailable_profiles(store,monkeypatch):
    seen=[]
    def respond(request):
        seen.append((request.method,request.url.path,request.headers.get('authorization')))
        if request.url.path=='/api/tags':
            return httpx.Response(200,json={'models':[{'name':'phi4:14b'},{'name':'nemotron-3.5-bolt:e4b-q4_K_M'}]})
        return httpx.Response(200,json={'data':[{'id':'nvidia/nemotron-super'}]})
    fake_backend(monkeypatch,respond)
    with TestClient(create_app(store)) as client:
        found=client.post('/api/llm/discover',json={'connection_type':'ollama','base_url':'http://gpu.local:11434/v1'}).json()
        assert found['models']==['nemotron-3.5-bolt:e4b-q4_K_M','phi4:14b']
        saved=client.post('/api/llm/adapters',json={**profile(connection_type='openai',base_url='https://tf.local/v1',model='nvidia/nemotron-super').model_dump(),'api_key':'test-key'}).json()
        assert client.post('/api/llm/discover',json={'connection_type':'openai','base_url':'https://tf.local/v1','adapter_id':saved['id']}).json()['models']==['nvidia/nemotron-super']
        assert seen[-1]==('GET','/v1/models','Bearer test-key')
        assert client.get(f"/api/llm/adapters/{saved['id']}/status").json()['available'] is True
        missing=client.post('/api/llm/adapters',json=profile(model='nemotron-3-nano:4b-q8_0').model_dump()).json()
        status=client.get(f"/api/llm/adapters/{missing['id']}/status").json()
        assert status['available'] is False and 'not offered' in status['message']
        assert missing['id'] in [a['id'] for a in client.get('/api/llm/adapters').json()['adapters']]
    assert all(method=='GET' for method,*_ in seen)


def test_unreachable_connection_reports_status_without_raising(store,monkeypatch):
    def respond(request):raise httpx.ConnectError('down')
    fake_backend(monkeypatch,respond)
    registry=LLMRegistry(store);saved=registry.save(profile())
    import asyncio
    status=asyncio.run(registry.status(saved['id']))
    assert status['available'] is False and 'Could not reach' in status['message']


async def test_effective_models_match_the_models_actually_invoked(store,monkeypatch):
    from services.ai_orchestrator.two_stage import decompose,bind_tasks,effective_models,save_settings
    from shared.models.robotics import RoleSettings,FunctionCall
    calls=[]
    def respond(request):
        body=json.loads(request.content);calls.append(body['model'])
        if 'PLANNER' in body['messages'][0]['content']:
            task=TaskDefinition(id='point',name='Point',intent='Move shoulder',operation='command',robot_id='arm_01',binding_status='unresolved')
            answer={'status':'ready','tasks':[task.model_dump()]}
        else:
            answer={'calls':[{'function':'set_shoulder','arguments':{'value':.3,'unit':'rad'}}]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(answer)},'finish_reason':'stop'}]})
    fake_backend(monkeypatch,respond)
    registry=LLMRegistry(store)
    default=registry.save(profile(name='Default',model='default-model'))
    planner=registry.save(profile(name='Planner',model='planner-model'))
    override=registry.save(profile(name='Override',model='override-model'))
    save_settings(registry,RoleSettings(planner_adapter_id=planner['id']))
    runtime=SimulationController(store)
    try:
        *_,cell,_=await runtime.context('apple_transfer');states=await runtime.states(cell)
        definition=PlanDefinition(id='p',project_id='apple_transfer',name='p',goal='Point the shoulder')
        before=effective_models(registry,definition)
        assert (before['planner']['model'],before['planner']['source'])==('planner-model','workspace role')
        assert (before['binder']['model'],before['binder']['source'])==('default-model','workspace default')
        assert before['custom'] and 'Task planner uses Planner' in before['explanations'][0]
        proposal=await decompose(registry,definition,cell,states,'snap')
        definition.tasks=proposal.tasks;definition.tasks[0].llm_adapter_id=override['id']
        assert not await bind_tasks(registry,definition,cell,cell.objects)
        after=effective_models(registry,definition)
        assert after['tasks']['point']['model']=='override-model'
        assert calls==['planner-model','override-model']
        assert [e.model for e in definition.inference_evidence]==calls
        assert default['id']==after['default_id']
    finally:await runtime.close()


ACTUATOR_DOC='''TestArm SDK. client.set_base(angle_rad) rotates the base, range -3.14 to 3.14 rad.
client.set_shoulder(angle_rad) rotates the shoulder, range -1.5 to 2.8 rad.
client.stop() stops all motion.'''


def generated(client_factory=''):
    return json.dumps({'functions':[
        {'id':'base','vendor_method':'set_base','argument':'value','mode':'position','unit':'rad','minimum':-3.14,'maximum':3.14,
         'documentation_quote':'client.set_base(angle_rad) rotates the base, range -3.14 to 3.14 rad.','write_style':'single','vendor_joint':''},
        {'id':'shoulder','vendor_method':'set_shoulder','argument':'value','mode':'position','unit':'rad','minimum':-1.5,'maximum':9.9,
         'documentation_quote':'client.set_shoulder(angle_rad) rotates the shoulder, range -1.5 to 2.8 rad.','write_style':'single','vendor_joint':''}],
        'sdk_module':'','client_factory':client_factory,'feedback_method':'','stop_method':'stop','disconnect_method':'','watchdog_method':''})


@pytest.mark.parametrize('category',['physical','virtual'])
def test_incomplete_generation_returns_recoverable_function_table_without_inventing_sdk_details(store,monkeypatch,category):
    fake_backend(monkeypatch,lambda request:httpx.Response(200,json={'choices':[{'message':{'content':generated()},'finish_reason':'stop'}]}))
    with TestClient(create_app(store)) as client:
        client.post('/api/llm/adapters',json=profile().model_dump())
        body={'name':'TestArm','category':category,'sdk_version':'1.0','documentation':ACTUATOR_DOC}
        result=client.post('/api/library/drivers/generate-draft',json=body).json()
        assert result['status']=='needs_information' and result['failure_id']
        rows={f['id']:f for f in result['draft']['functions']}
        assert rows['base']['valid'] and not rows['shoulder']['valid']
        fields={i['field'] for i in result['issues']}
        assert any(f.startswith('functions[1]') for f in fields)
        if category=='physical':
            assert {'sdk_module','client_factory'}<=fields and result['draft']['client_factory']==''
        else:
            assert not {'sdk_module','client_factory'}&fields and result['draft']['client_factory']=='Client'
        assert result['draft']['stop_method']=='stop'
        # The original complete-manifest endpoint keeps failing loudly.
        assert client.post('/api/library/drivers/generate',json=body).status_code==422
        assert client.get('/api/library/drivers').json()==[]


def test_virtual_generation_with_blank_factory_completes(store,monkeypatch):
    answer=json.loads(generated());answer['functions']=answer['functions'][:1]
    fake_backend(monkeypatch,lambda request:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(answer)},'finish_reason':'stop'}]}))
    with TestClient(create_app(store)) as client:
        client.post('/api/llm/adapters',json=profile().model_dump())
        result=client.post('/api/library/drivers/generate-draft',json={'name':'TestArm','category':'virtual','sdk_version':'1.0','documentation':ACTUATOR_DOC}).json()
        assert result['status']=='complete' and result['driver']['definition']['client_factory']=='Client'
        assert result['provenance']['model']=='nemotron-3.5-bolt:e4b-q4_K_M'


def test_simulator_adapter_is_derived_from_reviewed_joints_and_passes_contract_tests(store):
    with TestClient(create_app(store)) as client:
        driver=client.post('/api/library/drivers/simulator/demo_arm')
        assert driver.status_code==201,driver.text
        driver=driver.json()
        functions={f['id']:f for f in driver['definition']['functions']}
        assert set(functions)=={'set_base_yaw','set_shoulder','set_elbow','set_wrist','set_gripper'}
        assert (functions['set_shoulder']['minimum'],functions['set_shoulder']['maximum'])==(-1.5,2.8)
        assert driver['definition']['category']=='virtual' and driver['reviewed_hash'] is None
        client.post(f"/api/library/drivers/{driver['id']}/review",json={'expected_hash':driver['hash']}).raise_for_status()
        report=client.post(f"/api/library/drivers/{driver['id']}/test").json()
        assert report['test_report']['passed']


def test_plan_can_choose_planner_and_task_llms_independently(store,monkeypatch):
    with TestClient(create_app(store)) as client:
        a=client.post('/api/llm/adapters',json=profile(name='Planner',model='planner-model').model_dump()).json()
        b=client.post('/api/llm/adapters',json=profile(name='Task',model='task-model').model_dump()).json()
        p=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'Roles','goal':'Point'}).json()
        url=f"/api/projects/apple_transfer/plan-definitions/{p['id']}"
        client.put(url+'/roles',json={'planner_adapter_id':a['id'],'binding_adapter_id':b['id'],'vision_enabled':False}).raise_for_status()
        models=client.get(url+'/effective-models').json()
        assert (models['planner']['model'],models['planner']['source'])==('planner-model','plan')
        assert (models['binder']['model'],models['binder']['source'])==('task-model','plan')
        client.put(url+'/roles',json={'planner_adapter_id':None,'binding_adapter_id':b['id'],'vision_enabled':False}).raise_for_status()
        models=client.get(url+'/effective-models').json()
        assert models['planner']['source']!='plan' and models['binder']['model']=='task-model'


def test_business_command_records_its_planner_and_task_llms(store,monkeypatch):
    def respond(request):
        body=json.loads(request.content)
        if 'PLANNER' in body['messages'][0]['content']:
            task=TaskDefinition(id='point',name='Point',intent='Move shoulder',operation='command',robot_id='arm_01',binding_status='unresolved')
            answer={'status':'ready','tasks':[task.model_dump()]}
        else:answer={'calls':[{'function':'set_shoulder','arguments':{'value':.3,'unit':'rad'}}]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(answer)},'finish_reason':'stop'}],'model':body['model']})
    fake_backend(monkeypatch,respond)
    import uuid
    with TestClient(create_app(store)) as client:
        a=client.post('/api/llm/adapters',json=profile(name='Planner',model='planner-model').model_dump()).json()
        b=client.post('/api/llm/adapters',json=profile(name='Task',model='task-model').model_dump()).json()
        choice=client.get('/api/business/ai-models').json()
        assert {m['model'] for m in choice['models']}=={'planner-model','task-model'}
        job=client.post('/api/business/projects/apple_transfer/commands',json={'instruction':'Point the shoulder','request_id':str(uuid.uuid4()),
            'planner_adapter_id':a['id'],'task_adapter_id':b['id']})
        assert job.status_code==201,job.text
        assert job.json()['ai_models']=={'planner':'planner-model','task':'task-model'}


def test_task_llm_calls_are_completed_only_where_the_catalog_is_unambiguous(model):
    from services.ai_orchestrator.two_stage import complete_call,normalize_call
    call=complete_call({'function':'set_wrist','target':'wrist','arguments':{'value':0.5,'unit':'radians'}},model)
    assert call.arguments=={'value':0.5,'unit':'rad'} and normalize_call(call,model)['joint']=='wrist'
    assert complete_call({'function':'set_wrist','arguments':{'value':0.5}},model).arguments['unit']=='rad'
    move=complete_call({'function':'MOVE','position':[0.3,0,0.3]},model)
    assert move.arguments['target']=='parallel_gripper' and move.arguments['frame']==model['kinematics']['world_frame']
    normalize_call(move,model)
    # A wrong unit or an out-of-range value is still rejected, never converted.
    with pytest.raises(ValueError):normalize_call(complete_call({'function':'set_wrist','arguments':{'value':0.5,'unit':'deg'}},model),model)
    with pytest.raises(ValueError):normalize_call(complete_call({'function':'set_wrist','arguments':{'value':99}},model),model)


def test_move_catalog_lists_only_callable_arguments_and_redundant_base_frame_is_dropped(model):
    from services.ai_orchestrator.two_stage import catalog,complete_call,normalize_call
    move=next(f for f in catalog(model) if f['id']=='MOVE')
    assert 'base_frame' not in move['arguments'] and move['frames']=={'tool':model['kinematics']['world_frame']}
    call=complete_call({'function':'MOVE','arguments':{'target':'parallel_gripper','position':[0.3,0,0.3],'frame':'world','base_frame':'world'}},model)
    assert 'base_frame' not in call.arguments and normalize_call(call,model)['kind']=='tool'
    conflicting=complete_call({'function':'MOVE','arguments':{'position':[0.3,0,0.3],'frame':'world','base_frame':'map'}},model)
    with pytest.raises(ValueError,match='base_frame'):normalize_call(conflicting,model)


def test_planner_task_commands_are_discarded_before_validation():
    from services.ai_orchestrator.two_stage import Proposal,intent_only
    raw={'status':'ready','tasks':[{'id':'t1','name':'Move','intent':'Move tool','operation':'command','robot_id':'arm_01',
        'command':{'type':'MOVE_END_EFFECTOR','position_unit':'m'},'target':{'x':1},'function_calls':[{'function':'MOVE'}]}]}
    task=Proposal.model_validate(intent_only(raw)).tasks[0]
    assert task.command is None and task.target is None and task.function_calls==[] and task.intent=='Move tool'


async def test_task_llm_gets_one_formatting_repair(store,monkeypatch):
    from services.ai_orchestrator.two_stage import bind_tasks
    answers=iter(['{"calls":[{"function":"set_shoulder" "arguments":{}}]}','{"calls":[{"function":"set_shoulder","arguments":{"value":0.3,"unit":"rad"}}]}'])
    fake_backend(monkeypatch,lambda request:httpx.Response(200,json={'choices':[{'message':{'content':next(answers)},'finish_reason':'stop'}]}))
    registry=LLMRegistry(store);registry.save(profile())
    runtime=SimulationController(store)
    try:
        *_,cell,_=await runtime.context('apple_transfer')
        definition=PlanDefinition(id='p',project_id='apple_transfer',name='p',tasks=[TaskDefinition(id='t',name='Point',intent='Shoulder 0.3',operation='command',robot_id='arm_01',binding_status='unresolved')])
        assert not await bind_tasks(registry,definition,cell,cell.objects)
        assert definition.tasks[0].function_calls[0].arguments=={'value':0.3,'unit':'rad'}
        assert len([e for e in definition.inference_evidence if e.stage=='binder'])==2
    finally:await runtime.close()


def test_single_tool_move_and_grasp_are_completed_without_changing_intent(model):
    from services.ai_orchestrator.two_stage import catalog,complete_call,normalize_call
    assert 'parallel_gripper' in next(f for f in catalog(model) if f['id']=='MOVE')['arguments']['target']
    for label in ('arm_01','configured end-effector ID or base',None):
        assert normalize_call(complete_call({'function':'MOVE','arguments':{'target':label,'position':[0.3,0,0.3]}},model),model)['target']=='parallel_gripper'
    with pytest.raises(ValueError):normalize_call(complete_call({'function':'MOVE','arguments':{'target':'base','position':[0.3,0]}},model),model)
    assert complete_call({'function':'GRASP','arguments':{'object_id':'apple','target_id':'table1'}},model).arguments=={'object_id':'apple'}


def test_move_position_text_in_catalog_notation_is_parsed(model):
    from services.ai_orchestrator.two_stage import complete_call,normalize_call
    call=complete_call({'function':'MOVE','arguments':{'target':'parallel_gripper','position':'[0.34, -0.16, 0.2] metres','frame':'world'}},model)
    assert call.arguments['position']==[0.34,-0.16,0.2] and normalize_call(call,model)['kind']=='tool'
    for text in ('[0.3, 0, 0.3] feet','near the apple','[0.3, apple, 0.3]'):
        with pytest.raises(ValueError):normalize_call(complete_call({'function':'MOVE','arguments':{'position':text}},model),model)

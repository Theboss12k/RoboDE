import asyncio
import json
import os
import stat
import httpx
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.api.storage import fingerprint
from services.execution.controller import SimulationController
from services.ai_orchestrator.llm import ProviderConfiguration,LLMRegistry
from shared.models.domain import PlanDefinition,TaskDefinition


@pytest.mark.parametrize('answer', ['{"tasks":[]}', '```json\n{"tasks":[]}\n```', '```\n{"tasks":[]}\n```', '```json\n{"tasks":[]}\n```\n### Explanation\nReview these tasks.',
                                    'Here is the corrected JSON instance:\n\n```json\n{"tasks":[]}\n```'])
def test_local_model_json_formatting(answer):
    from services.ai_orchestrator.llm import json_answer
    assert json_answer(answer) == {'tasks': []}


@pytest.mark.parametrize('answer', ['Here is the plan: {"tasks":[]}', '```json\n{}\n```\n```json\n{}\n```', '```python\n{}\n```', '```json\n{}',
                                    'Intro:\n```json\n{}\n```\n```json\n{}\n```', 'Intro:\n```python\n{}\n```', 'Intro:\n```json\n{}', 'Use {"a":1}\n```json\n{}\n```'])
def test_local_model_json_rejects_prose_multiple_fences_and_truncation(answer):
    from services.ai_orchestrator.llm import json_answer
    with pytest.raises(ValueError):
        json_answer(answer)

@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    for key in ('AI_BASE_URL','AI_MODEL','AI_API_KEY'):
        monkeypatch.delenv(key,raising=False)


def configuration(**kw):
    return ProviderConfiguration(name='Local model',base_url='http://llm.local/v1',model='test-model',**kw)


def fake_provider(monkeypatch,handler):
    original=httpx.AsyncClient
    monkeypatch.setattr('services.ai_orchestrator.llm.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


def test_global_multiple_profiles_credentials_and_function_contract(store,monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'Hello from the configured function'}}],'usage':{'total_tokens':12}})
    fake_provider(monkeypatch,respond)
    with TestClient(create_app(store)) as client:
        first=client.post('/api/llm/adapters',json=configuration(api_key='private-test-value',system_prompt='Base system').model_dump())
        assert first.status_code==201,first.text
        a=first.json()
        second=client.post('/api/llm/adapters',json={**configuration().model_dump(),'name':'Another adapter','model':'other-model'}).json()
        assert a['id']!=second['id']
        data=client.get('/api/llm/adapters').json()
        assert len(data['adapters'])==2 and data['default_id']==a['id']
        assert 'private-test-value' not in json.dumps(data) and a['has_api_key']
        answer=client.post(f"/api/llm/adapters/{a['id']}/invoke",json={'input':'User input','system_prompt':'Call system'}).json()
        assert answer['answer']=='Hello from the configured function'
        sent=json.loads(calls[-1].content)
        assert sent['messages']==[{'role':'system','content':'Base system\n\nCall system'},{'role':'user','content':'User input'}]
        assert calls[-1].headers['authorization']=='Bearer private-test-value'
        assert stat.S_IMODE((store.runtime/'llm/secrets.json').stat().st_mode)==0o600
        assert client.put('/api/llm/default',json={'adapter_id':second['id']}).status_code==200
        updated=client.put(f"/api/llm/adapters/{a['id']}",json=configuration().model_dump()).json()
        assert updated['version']==2 and updated['has_api_key']
        assert client.delete(f"/api/llm/adapters/{second['id']}").status_code==200
        assert client.get('/api/llm/adapters').json()['default_id'] is None
    assert len(LLMRegistry(store).all()['adapters'])==1


async def test_llm_dag_answers_dependencies_immutable_history_and_stale_config(store,monkeypatch):
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'First answer' if len(requests)==1 else 'Second answer'}}]})
    fake_provider(monkeypatch,respond)
    runtime=SimulationController(store,speed=2000)
    first=runtime.llm.save(configuration())
    second=runtime.llm.save(configuration())
    *_,session,_=await runtime.context('apple_transfer')
    initial=(await runtime.states(session))['arm_01'].positions.copy()
    definition=PlanDefinition(id='llm_plan',project_id='apple_transfer',name='LLM pipeline',tasks=[
        TaskDefinition(id='draft',name='Draft analysis',operation='llm',llm_input='Analyze this request',llm_adapter_id=first['id'],llm_system_prompt='private task instructions'),
        TaskDefinition(id='summarize',name='Summarize',operation='llm',dependencies=['draft'],llm_adapter_id=second['id'],llm_input='Summarize {{tasks.draft.answer}}'),
        TaskDefinition(id='home',name='Home',robot_id='arm_01',operation='move',dependencies=['summarize'])])
    store.save_definition(definition)
    from services.planning.definitions import compile_definition
    snapshot=await runtime.snapshot('apple_transfer')
    plan=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock')
    assert plan.valid,plan.checks
    assert 'private task instructions' not in plan.code and 'llm_system_prompt' not in plan.code
    assert plan.atomic_tasks[0].robot_id==''
    store.save_plan(plan,snapshot)
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,'apple_transfer')
    await runtime.jobs[run.id]
    assert run.status=='SIMULATION_PASSED',run.logs
    assert run.evidence['llm']['draft']['answer']=='First answer'
    assert run.evidence['llm']['summarize']['adapter_id']==second['id']
    assert requests[1]['messages'][-1]['content']=='Summarize First answer'
    assert run.task_statuses=={'draft':'completed','summarize':'completed','home':'completed'}
    assert (await runtime.states(session))['arm_01'].positions==initial
    assert store.get_run(run.id).evidence['llm']['summarize']['answer']=='Second answer'
    runtime.llm.save(configuration(system_prompt='changed'),first['id'])
    with pytest.raises(ValueError,match='stale'):
        await runtime.execute_registered_plan(plan.id,plan.fingerprint,'apple_transfer')
    assert store.get_run(run.id).evidence['llm']['draft']['answer']=='First answer'
    await runtime.close()


async def test_llm_cancellation_and_error_stop_cell(store,monkeypatch):
    entered=asyncio.Event();cancelled=asyncio.Event()
    async def slow(request):
        entered.set()
        try:await asyncio.sleep(20)
        finally:cancelled.set()
        return httpx.Response(200,json={})
    fake_provider(monkeypatch,slow)
    runtime=SimulationController(store,speed=1000)
    adapter=runtime.llm.save(configuration())
    *_,session,_=await runtime.context('apple_transfer')
    from services.planning.definitions import compile_definition
    definition=PlanDefinition(id='cancel_llm',project_id='apple_transfer',name='Cancel LLM',tasks=[TaskDefinition(id='answer',name='Answer',operation='llm',llm_adapter_id=adapter['id'],llm_input='Wait')])
    store.save_definition(definition);snapshot=await runtime.snapshot('apple_transfer')
    plan=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock');store.save_plan(plan,snapshot)
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,'apple_transfer')
    await asyncio.wait_for(entered.wait(),2)
    runtime.stop(run.id)
    await asyncio.wait_for(runtime.jobs[run.id],3)
    assert cancelled.is_set() and run.status=='CANCELLED' and run.stopped_verified
    assert not run.evidence.get('llm') and not runtime.leases
    await runtime.close()


def test_task_refinement_is_validated_proposal_and_selected_adapter_used(store,monkeypatch):
    replies=[];calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(replies.pop(0))}}]})
    fake_provider(monkeypatch,respond)
    with TestClient(create_app(store)) as client:
        adapter=client.post('/api/llm/adapters',json=configuration().model_dump()).json()
        definition=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'Refine'}).json()
        path=f"/api/projects/apple_transfer/plan-definitions/{definition['id']}"
        task=TaskDefinition(id='home',name='Home',operation='move',robot_id='arm_01',llm_adapter_id=adapter['id']).model_dump()
        saved=client.put(path,json={'name':'Refine','goal':'','version':1,'tasks':[task]}).json()
        replies.append({**task,'name':'Return home carefully'})
        response=client.post(path+'/tasks/home/refine',json={'version':saved['version'],'instruction':'Improve name'})
        assert response.status_code==200,response.text
        assert response.json()['task']['name']=='Return home carefully'
        assert client.get(path).json()['tasks'][0]['name']=='Home'
        replies.append({**task,'robot_id':'made_up_robot'})
        assert client.post(path+'/tasks/home/refine',json={'version':saved['version'],'instruction':'Improve'}).status_code==422
        assert calls[0]['model']=='test-model'


def test_llm_validation_rejects_unconfigured_and_invalid_references(store):
    with TestClient(create_app(store)) as client:
        definition=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'LLM'}).json()
        path=f"/api/projects/apple_transfer/plan-definitions/{definition['id']}"
        task=TaskDefinition(id='answer',name='Answer',operation='llm',llm_input='Question').model_dump()
        assert client.put(path,json={'name':'LLM','goal':'','version':1,'tasks':[task]}).status_code==200
        response=client.post(path+'/compile')
        assert response.status_code==422 and 'LLM adapter' in response.text
        task['llm_input']='{{tasks.missing.answer}}'
        assert client.put(path,json={'name':'LLM','goal':'','version':2,'tasks':[task]}).status_code==422
        task.update(llm_input='Question',robot_id='arm_01')
        assert client.put(path,json={'name':'LLM','goal':'','version':2,'tasks':[task]}).status_code==422
        assert client.post('/api/llm/adapters',json={**configuration().model_dump(),'base_url':'file:///private'}).status_code==422


def test_provider_failures_hide_secrets(store,monkeypatch):
    def respond(request):return httpx.Response(401,text='private-test-value')
    fake_provider(monkeypatch,respond)
    with TestClient(create_app(store)) as client:
        adapter=client.post('/api/llm/adapters',json=configuration(api_key='private-test-value').model_dump()).json()
        response=client.post(f"/api/llm/adapters/{adapter['id']}/invoke",json={'input':'Hello'})
        assert response.status_code==422 and 'private-test-value' not in response.text


def test_explicit_local_default_is_preserved_with_legacy_environment_provider(store,monkeypatch):
    monkeypatch.setenv('AI_BASE_URL','http://environment.local/v1')
    monkeypatch.setenv('AI_MODEL','environment-model')
    registry=LLMRegistry(store)
    assert registry.all()['default_id']=='environment'
    data=registry.all();data['default_id']=None;registry.write(data)
    assert registry.all()['default_id'] is None
    from services.ai_orchestrator.providers import get_provider
    assert get_provider(registry).name=='Local templates'


async def test_llm_failure_stops_cell_and_preserves_unexecuted_dependents(store,monkeypatch):
    def error(request):return httpx.Response(503,text='Unavailable')
    fake_provider(monkeypatch,error)
    runtime=SimulationController(store,speed=1000)
    adapter=runtime.llm.save(configuration())
    *_,session,_=await runtime.context('apple_transfer')
    from services.planning.definitions import compile_definition
    definition=PlanDefinition(id='failed_llm',project_id='apple_transfer',name='Failure',tasks=[
        TaskDefinition(id='answer',name='Answer',operation='llm',llm_adapter_id=adapter['id'],llm_input='Question'),
        TaskDefinition(id='home',name='Home',operation='move',robot_id='arm_01',dependencies=['answer'])])
    store.save_definition(definition);snapshot=await runtime.snapshot('apple_transfer')
    plan=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock');store.save_plan(plan,snapshot)
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,'apple_transfer')
    await runtime.jobs[run.id]
    assert run.status=='FAILED' and run.stopped_verified
    assert not run.evidence.get('llm') and 'home' not in run.task_statuses
    assert not runtime.resources.owners and not runtime.leases
    await runtime.close()


async def test_sdk_drafting_uses_global_function_and_records_provider_provenance(store,monkeypatch):
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'class Transport:\n    def command(self, positions):\n        raise NotImplementedError("Review vendor API")\n'}}]})
    fake_provider(monkeypatch,respond)
    registry=LLMRegistry(store);provider=registry.save(configuration())
    from services.adapters.generation import AdapterRegistry,GenerateAdapter
    initial=store.load_project('apple_transfer')[1][0]['initial_configuration']['actuator_positions']
    adapter=await AdapterRegistry(store).generate(GenerateAdapter(model_id='demo_arm',name='Custom SDK',kind='sdk',documentation='Documented vendor contract',sdk_version='1.2'),initial)
    assert adapter['provenance']['llm_adapter']=={'adapter_id':provider['id'],'adapter_version':1,'model':'test-model'}
    assert requests[0]['model']=='test-model'
    assert adapter['live_eligible'] is False and adapter['validation_status']=='draft'


async def test_llm_only_plan_supports_configuration_only_models_without_joint_commands(store,monkeypatch):
    with TestClient(create_app(store)) as client:
        data=client.get('/api/registry/demo_arm/bundle').json()
        data['robot']['id']='config_only';data['kinematics']['solver']='unverified'
        assert client.post('/api/registry/import',json=data).status_code==201
        assert client.post('/api/projects/apple_transfer/robots',json={'id':'custom','name':'Custom','model_id':'config_only','base_pose':{'x':0,'y':2,'z':0,'yaw':0}}).status_code==201
    fake_provider(monkeypatch,lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'A data-only answer'}}]}))
    runtime=SimulationController(store,speed=1000);provider=runtime.llm.save(configuration())
    *_,session,_=await runtime.context('apple_transfer')
    async def forbidden_command(positions):raise AssertionError('An LLM-only run must never command joints')
    for adapter in session.adapters.values():adapter.command=forbidden_command
    definition=PlanDefinition(id='only_llm',project_id='apple_transfer',name='No motion',tasks=[TaskDefinition(id='answer',name='Answer',operation='llm',llm_input='Question',llm_adapter_id=provider['id'])])
    store.save_definition(definition)
    from services.planning.definitions import compile_definition
    snapshot=await runtime.snapshot('apple_transfer')
    plan=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock');store.save_plan(plan,snapshot)
    assert plan.valid,plan.checks
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,'apple_transfer')
    await runtime.jobs[run.id]
    assert run.status=='SIMULATION_PASSED',run.logs
    assert run.evidence['llm']['answer']['answer']=='A data-only answer'
    await runtime.close()


def test_prompts_private_and_preserved_when_editing_through_ui(store):
    with TestClient(create_app(store)) as client:
        data=configuration(system_prompt='internal legacy prefix').model_dump()
        adapter=client.post('/api/llm/adapters',json=data).json()
        assert 'system_prompt' not in adapter
        assert 'internal legacy prefix' not in client.get('/api/llm/adapters').text
        data.pop('system_prompt');data['name']='Edited in UI'
        assert client.put(f"/api/llm/adapters/{adapter['id']}",json=data).status_code==200
        assert client.put('/api/llm/default',json={'adapter_id':adapter['id']}).status_code==200
        registry=LLMRegistry(store)
        assert registry.resolve(adapter['id'])['system_prompt']=='internal legacy prefix'
        assert 'internal legacy prefix' not in json.dumps(registry.snapshot())


async def test_code_adapter_separate_worker_contract_and_environment(store,monkeypatch):
    monkeypatch.setenv('PRIVATE_UNRELATED_SECRET','do not inherit')
    source='''import os, json
async def invoke(input: str, system_prompt: str) -> str:
    print('provider diagnostic should not corrupt the answer')
    return json.dumps({'pid':os.getpid(),'input':input,'instructions':bool(system_prompt),
        'unrelated':os.getenv('PRIVATE_UNRELATED_SECRET'),'model':os.getenv('ROBOT_IDE_LLM_MODEL'),
        'key':bool(os.getenv('ROBOT_IDE_LLM_API_KEY'))})
'''
    registry=LLMRegistry(store)
    adapter=registry.save(configuration(protocol='python_function',source_code=source,api_key='test-credential'))
    result=json.loads((await registry.adapter(adapter['id'])('Hello','private instructions'))['answer'])
    assert result==dict(pid=result['pid'],input='Hello',instructions=True,unrelated=None,model='test-model',key=True)
    assert result['pid']!=os.getpid()


@pytest.mark.parametrize('source',[
    'def other(input, system_prompt): return input',
    'async def invoke(input): return input',
    'def invoke(input, system_prompt, extra): return input',
    'def invoke(*args): return "answer"',
    'this is not python!',
])
def test_code_adapter_signature_validation(store,source):
    with pytest.raises(ValueError):
        LLMRegistry(store).save(configuration(protocol='python_function',source_code=source))
    assert not LLMRegistry(store).all()['adapters']


@pytest.mark.parametrize('body',['return {}','return ""','raise RuntimeError(system_prompt)'])
async def test_code_adapter_invalid_answers_and_errors_hide_instructions(store,body):
    registry=LLMRegistry(store)
    adapter=registry.save(configuration(protocol='python_function',source_code=f'async def invoke(input, system_prompt):\n    {body}\n'))
    with pytest.raises(ValueError) as error:
        await registry.adapter(adapter['id'])('Hello','private instructions')
    assert 'private instructions' not in str(error.value)


@pytest.mark.parametrize('cancel',[False,True])
async def test_code_worker_timeout_and_cancel_terminate_process(store,tmp_path,cancel):
    marker=tmp_path/'worker.pid'
    source=f'''import os, asyncio
async def invoke(input, system_prompt):
    with open({str(marker)!r},'w') as f: f.write(str(os.getpid()))
    await asyncio.sleep(60)
    return 'should never complete'
'''
    registry=LLMRegistry(store)
    adapter=registry.save(configuration(protocol='python_function',source_code=source,timeout_seconds=1))
    job=asyncio.create_task(registry.adapter(adapter['id'])('Hello','private instructions'))
    for _ in range(100):
        if marker.exists():break
        await asyncio.sleep(.01)
    assert marker.exists()
    pid=int(marker.read_text())
    if cancel:
        job.cancel()
        with pytest.raises(asyncio.CancelledError):await job
    else:
        with pytest.raises(ValueError):await job
    with pytest.raises(ProcessLookupError):os.kill(pid,0)


@pytest.mark.parametrize('choice,expected',[
    ({'message':{'content':'{"tasks":[]}'},'finish_reason':'length'},'token limit'),
    ({'message':{'content':'<think>still reasoning'},'finish_reason':'stop'},'token limit'),
    ({'message':{'content':None},'finish_reason':'stop'},'invalid answer'),
])
async def test_truncated_or_empty_chat_answers_are_rejected(store,monkeypatch,choice,expected):
    fake_provider(monkeypatch,lambda request:httpx.Response(200,json={'choices':[choice]}))
    adapter=LLMRegistry(store).save(configuration())
    with pytest.raises(ValueError,match=expected):
        await LLMRegistry(store).adapter(adapter['id'])('Plan','')


async def test_chat_answer_records_provider_host_and_strips_reasoning(store,monkeypatch):
    from services.ai_orchestrator.llm import json_answer
    body={'choices':[{'message':{'content':'<think>plan steps</think>\n{"calls":[]}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':9,'completion_tokens':4}}
    fake_provider(monkeypatch,lambda request:httpx.Response(200,json=body))
    adapter=LLMRegistry(store).save(configuration())
    answer=await LLMRegistry(store).adapter(adapter['id'])('Plan','')
    assert answer['provider_host']=='llm.local' and answer['finish_reason']=='stop' and answer['usage']=={'prompt_tokens':9,'completion_tokens':4}
    assert json_answer(answer['answer'])=={'calls':[]}

import asyncio
import json
import time
import pytest


def test_local_sdk_python_fence_with_review_explanation():
    from services.adapters.generation import sdk_source_answer
    source = 'class Transport:\n    def command(self, positions):\n        raise NotImplementedError("Missing vendor writer")'
    assert sdk_source_answer('```python\n'+source+'\n```\nThis requires vendor review.') == source
    for invalid in ['```python\nclass Transport:', '```json\n{}\n```', '```python\nx=1\n```\n```python\ny=2\n```']:
        with pytest.raises(ValueError):
            sdk_source_answer(invalid)
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.adapters.generation import AdapterProcess, AdapterRegistry, GenerateAdapter
from services.adapters.controls import ManualControls
from services.execution.controller import SimulationController
from shared.models.domain import PlanDefinition,TaskDefinition
from services.planning.definitions import compile_definition
from services.api.storage import fingerprint


async def test_generated_mapping_units_transport_and_stop(store,model,instance):
    registry=AdapterRegistry(store)
    mapping={k:'vendor_'+k for k in model['actuators']['actuators']}
    bundle=await registry.generate(GenerateAdapter(model_id='demo_arm',name='Mapped simulation',kind='mock',joint_mapping=mapping,
        remote_units={k:('deg' if a['unit']=='rad' else 'mm') for k,a in model['actuators']['actuators'].items()}),instance['initial_configuration']['actuator_positions'])
    registry.review(bundle['id'],bundle['hash'])
    tested=await registry.test(bundle['id'])
    assert tested['test_report']['passed'] and tested['test_report']['hardware_validated'] is False
    assert (registry.active/(bundle['id']+'.json')).exists()
    assert (registry.path(bundle['id']).parent/'adapter.py').exists()
    process=AdapterProcess()
    try:
        await process.start(bundle)
        q={k:(a['min']+a['max'])/2 for k,a in bundle['controls'].items()}
        state=await process.request({'operation':'command','positions':q})
        assert state['positions']==pytest.approx(q)
        assert set(state['translated_command'])==set(mapping.values())
        assert state['source']=='simulation'
        stopped=await process.request({'operation':'stop'})
        assert stopped['stopped']
        with pytest.raises(ValueError):
            await process.request({'operation':'command','positions':{**q,'gripper':999}})
    finally:
        await process.close()


async def test_sdk_needs_provider_and_review_hash_cannot_be_reused(store,instance,monkeypatch):
    monkeypatch.delenv('AI_BASE_URL',raising=False)
    monkeypatch.delenv('AI_MODEL',raising=False)
    registry=AdapterRegistry(store)
    initial=instance['initial_configuration']['actuator_positions']
    with pytest.raises(ValueError,match='AI_BASE_URL'):
        await registry.generate(GenerateAdapter(model_id='demo_arm',name='SDK',kind='sdk',sdk_version='1.0',documentation='Official controller documentation'),initial)
    bundle=await registry.generate(GenerateAdapter(model_id='demo_arm',name='Test',kind='mock'),initial)
    with pytest.raises(ValueError,match='changed'):
        registry.review(bundle['id'],'wrong-hash')
    raw=json.loads(registry.path(bundle['id']).read_text())
    raw['adapter_code']+='\nprint("must not run")\n'
    registry.path(bundle['id']).write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='changed'):
        registry.get(bundle['id'])


async def test_generated_worker_rejects_arbitrary_code(store,instance):
    registry=AdapterRegistry(store)
    bundle=await registry.generate(GenerateAdapter(model_id='demo_arm',name='Bad code',kind='mock'),instance['initial_configuration']['actuator_positions'])
    bundle['translation']='def translate(positions):\n    return __import__("os").environ\n'
    process=AdapterProcess()
    try:
        with pytest.raises(ValueError,match='Unsupported'):
            await process.start(bundle)
    finally:
        await process.close()


async def test_environment_control_owns_cell_and_expires_with_confirmed_stop(store):
    runtime=SimulationController(store,speed=1000)
    controls=ManualControls(AdapterRegistry(store),runtime)
    session=await controls.open('apple_transfer','arm_01','mock','environment')
    assert session['mode']=='environment' and not session['armed']
    with pytest.raises(ValueError,match='manual control'):
        runtime.ensure_idle('apple_transfer')
    with pytest.raises(ValueError,match='already controlled'):
        await controls.open('apple_transfer','arm_01','mock','environment')
    sid=session['id']
    q={**session['feedback']['positions'],'base_yaw':.02}
    moved=await controls.command(sid,q)
    assert moved['feedback']['positions']['base_yaw']==pytest.approx(.02)
    stopped=await controls.stop(sid)
    assert stopped['stop_requested'] and stopped['stopped_verified']
    controls.sessions[sid]['touched']=time.monotonic()-20
    await asyncio.sleep(1.2)
    assert sid not in controls.sessions
    runtime.ensure_idle('apple_transfer')
    await controls.close()
    await runtime.close()


async def test_ignored_or_stale_feedback_disarms_and_preserves_ownership(store):
    runtime=SimulationController(store)
    registry=AdapterRegistry(store)
    controls=ManualControls(registry,runtime)
    session=await controls.open('apple_transfer','arm_01','mock')
    original=controls.feedback
    async def stale(s):
        value=await original(s)
        value['measured_at']='2000-01-01T00:00:00+00:00'
        return value
    controls.feedback=stale
    controls.sessions[session['id']]['armed_until']=time.monotonic()+30
    with pytest.raises(ValueError,match='Fresh'):
        await controls.read(session['id'])
    assert not controls.sessions[session['id']]['armed_until']
    controls.feedback=original
    await controls.close()
    await runtime.close()


def test_generation_review_test_and_test_controls_api_never_contact_bridge(store,monkeypatch):
    # An unreachable physical URL cannot affect an injected simulated test.
    with TestClient(create_app(store)) as client:
        body={'model_id':'demo_arm','name':'ROS adapter','kind':'ros2','connection':{'bridge_url':'http://127.0.0.1:1','token_env':'ROS_BRIDGE_TOKEN'}}
        response=client.post('/api/projects/apple_transfer/adapters/generate',json=body)
        assert response.status_code==201,response.text
        bundle=response.json()
        assert bundle['category']=='physical'
        assert client.post(f"/api/adapters/{bundle['id']}/review",json={'expected_hash':bundle['hash']}).status_code==200
        assert client.post(f"/api/adapters/{bundle['id']}/test").json()['test_report']['passed']
        opened=client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':bundle['id']})
        assert opened.status_code==201,opened.text
        session=opened.json()
        assert session['feedback']['source']=='simulation'
        assert not session['armed']
        q={**session['feedback']['positions'],'base_yaw':.1}
        moved=client.post(f"/api/controls/{session['id']}/command",json={'positions':q})
        assert moved.status_code==200,moved.text
        assert moved.json()['feedback']['translated_command']['base_yaw']==.1
        assert client.post(f"/api/controls/{session['id']}/arm").status_code==422
        assert client.delete(f"/api/controls/{session['id']}").status_code==200


async def test_sdk_source_draft_is_not_executed(store,instance,monkeypatch):
    import httpx
    from services.adapters import generation
    monkeypatch.setenv('AI_BASE_URL','https://provider.example/v1')
    monkeypatch.setenv('AI_MODEL','test-model')
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):
            calls.append(kwargs['json'])
            return httpx.Response(200,request=httpx.Request('POST',args[0]),json={'choices':[{'message':{'content':'raise RuntimeError("SDK draft must never execute")'}}]})
    monkeypatch.setattr(generation.httpx,'AsyncClient',Client)
    registry=AdapterRegistry(store)
    bundle=await registry.generate(GenerateAdapter(model_id='demo_arm',name='SDK draft',kind='sdk',sdk_version='2.0',documentation='API reference'),instance['initial_configuration']['actuator_positions'])
    assert calls and bundle['sdk_source'].startswith('raise')
    registry.review(bundle['id'],bundle['hash'])
    assert (await registry.test(bundle['id']))['test_report']['passed']
    runtime=SimulationController(store)
    controls=ManualControls(registry,runtime)
    with pytest.raises(ValueError,match='test-only'):
        await controls.open('apple_transfer','arm_01',bundle['id'],'live')
    await controls.close()
    await runtime.close()


def test_instance_profiles_are_scoped_and_do_not_store_credentials(store):
    with TestClient(create_app(store)) as client:
        bundle=client.post('/api/projects/apple_transfer/adapters/generate',json={'model_id':'demo_arm','name':'ROS profile','kind':'ros2','connection':{'bridge_url':'http://127.0.0.1:1'}}).json()
        path='/api/projects/apple_transfer/robots/arm_01/connections'
        data={'name':'Controller host','adapter_id':bundle['id'],'connection':{'bridge_url':'http://127.0.0.1:2','token_env':'ROS_BRIDGE_TOKEN'}}
        response=client.post(path,json=data)
        assert response.status_code==201,response.text
        profile=response.json()
        assert client.get(path).json()[0]['adapter_hash']==bundle['hash']
        session=client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':bundle['id'],'profile_id':profile['id']}).json()
        assert session['feedback']['source']=='simulation'
        assert client.put(path+'/'+profile['id'],json=data).status_code==422
        assert client.delete('/api/controls/'+session['id']).status_code==200
        assert client.put(path+'/'+profile['id'],json=data).status_code==200
        assert client.post(path,json={**data,'connection':{'token':'secret'}}).status_code==422


def test_isolated_physical_adapter_test_works_with_disconnected_environment(store):
    with TestClient(create_app(store)) as client:
        bundle=client.post('/api/projects/apple_transfer/adapters/generate',json={'model_id':'demo_arm','name':'Offline test','kind':'ros2','connection':{'bridge_url':'http://127.0.0.1:1'}}).json()
        client.get('/api/projects/apple_transfer')
        assert client.post('/api/projects/apple_transfer/disconnect').status_code==200
        opened=client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':bundle['id']})
        assert opened.status_code==201,opened.text
        assert opened.json()['feedback']['source']=='simulation'
        assert client.get('/api/projects/apple_transfer').json()['environment_connected'] is False

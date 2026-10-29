import asyncio
import copy
import json
import math
import os
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.adapters.commands import AdapterCommand,CommandStep,CommandParameter,compile_recipe,validate_catalog,default_commands
from services.adapters.generation import AdapterRegistry,GenerateAdapter
from services.adapters.controls import ManualControls
from services.execution.controller import SimulationController
from services.ai_orchestrator.llm import LLMRegistry,ProviderConfiguration


def wave():
    return AdapterCommand(id='wave',name='Wave',steps=[*[CommandStep(operation='move',values={'base_yaw':value},duration=.1) for value in (.35,-.35,0.)],CommandStep(operation='feedback')])


async def generated(store,instance,commands,**kwargs):
    registry=AdapterRegistry(store)
    data=GenerateAdapter(model_id='demo_arm',name='Named commands',kind='sdk',target='physical',configuration_method='custom',commands=commands,**kwargs)
    bundle=await registry.generate(data,instance['initial_configuration']['actuator_positions'])
    registry.review(bundle['id'],bundle['hash']);bundle=await registry.test(bundle['id'])
    runtime=SimulationController(store);controls=ManualControls(registry,runtime)
    return registry,bundle,runtime,controls


async def test_physical_custom_wave_runs_real_translation_in_isolated_simulator(store,instance,monkeypatch):
    def no_provider(*args,**kwargs):raise AssertionError('Custom recipes work offline')
    monkeypatch.setattr(LLMRegistry,'adapter',no_provider)
    registry,bundle,runtime,controls=await generated(store,instance,[wave()],joint_mapping={k:'remote_'+k for k in instance['initial_configuration']['actuator_positions']},remote_units={'base_yaw':'deg'})
    assert bundle['category']=='physical' and bundle['configuration_method']=='custom'
    assert bundle['commands'][0]['id']=='wave'
    assert {'stop','feedback','set_joints','open_gripper','close_gripper'}.issubset({c['id'] for c in bundle['commands']})
    session=await controls.open('apple_transfer','arm_01',bundle['id'])
    sid=session['id'];before=(await runtime.context('apple_transfer'))[-1].positions.copy()
    started=await controls.named_command(sid,'wave',{})
    assert started['command_run']['status']=='running'
    assert controls.sessions[sid]['process'].process.pid!=os.getpid()
    await controls.sessions[sid]['command_job']
    observed=await controls.read(sid);report=observed['command_run']
    assert report['status']=='passed',report
    assert report['stopped_verified'] and report['hardware_validated'] is False
    assert report['trace'][0]['feedback']['translated_command']['remote_base_yaw']==pytest.approx(.35*180/math.pi)
    assert report['trace'][1]['feedback']['positions']['base_yaw']==pytest.approx(-.35)
    assert observed['feedback']['positions']==pytest.approx(before)
    assert (await runtime.context('apple_transfer'))[-1].positions==before
    assert registry.get(bundle['id'])['command_tests'][-1]['status']=='passed'
    await controls.close();await runtime.close()


async def test_stop_cancels_wait_and_prevents_later_steps_and_overlapping_commands(store,instance):
    command=AdapterCommand(id='slow',name='Slow',steps=[CommandStep(operation='wait',duration=10),CommandStep(operation='move',values={'base_yaw':.3})])
    registry,bundle,runtime,controls=await generated(store,instance,[command])
    session=await controls.open('apple_transfer','arm_01',bundle['id']);sid=session['id']
    await controls.named_command(sid,'slow',{})
    with pytest.raises(ValueError,match='already running'):await controls.named_command(sid,'slow',{})
    with pytest.raises(ValueError,match='running'):await controls.command(sid,session['feedback']['positions'])
    started=time.monotonic();stopped=await controls.stop(sid)
    assert time.monotonic()-started<1
    assert stopped['command_run']['status']=='cancelled' and stopped['stop_requested'] and stopped['stopped_verified']
    assert stopped['feedback']['positions']==session['feedback']['positions']
    assert registry.get(bundle['id'])['command_tests'][-1]['status']=='cancelled'
    await controls.close();await runtime.close()


async def test_preflight_rejects_later_limit_violation_before_any_motion(store,instance):
    command=AdapterCommand(id='bounded',name='Bounded',parameters={'angle':CommandParameter(min=-1000.,max=1000.,default=0.,unit='rad')},steps=[CommandStep(operation='move',values={'base_yaw':.1}),CommandStep(operation='move',values={'wrist':'$angle'})])
    registry,bundle,runtime,controls=await generated(store,instance,[command])
    session=await controls.open('apple_transfer','arm_01',bundle['id']);sid=session['id']
    with pytest.raises(ValueError,match='outside'):await controls.named_command(sid,'bounded',{'angle':999.})
    with pytest.raises(ValueError,match='parameter'):await controls.named_command(sid,'bounded',{'angle':True})
    with pytest.raises(ValueError,match='exactly once'):await controls.named_command(sid,'bounded',{'extra':0.})
    assert (await controls.read(sid))['feedback']['positions']==session['feedback']['positions']
    assert controls.sessions[sid]['command_run'] is None
    await controls.close();await runtime.close()


async def test_named_commands_are_test_only_review_bound_and_catalog_tamper_invalidates(store,instance):
    registry,bundle,runtime,controls=await generated(store,instance,[wave()])
    unreviewed=await registry.generate(GenerateAdapter(model_id='demo_arm',name='Unreviewed',kind='mock',commands=[wave()]),instance['initial_configuration']['actuator_positions'])
    s=await controls.open('apple_transfer','arm_01',unreviewed['id'])
    with pytest.raises(ValueError,match='Review'):await controls.named_command(s['id'],'wave',{})
    env=await controls.open('apple_transfer','arm_01','mock','environment')
    with pytest.raises(ValueError,match='isolated'):await controls.named_command(env['id'],'wave',{})
    raw=json.loads(registry.path(bundle['id']).read_text());raw['commands'][0]['steps'][0]['values']['base_yaw']=.6
    registry.path(bundle['id']).write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='changed'):registry.get(bundle['id'])
    await controls.close();await runtime.close()


def test_command_catalog_rejects_unknown_refs_units_and_unbounded_recipes(model,instance):
    controls=model['actuators']['actuators'];initial=instance['initial_configuration']['actuator_positions']
    cases=[AdapterCommand(id='bad',name='Bad',steps=[CommandStep(operation='move',values={'base_yaw':'__import__("os")'})]),
        AdapterCommand(id='bad',name='Bad',steps=[CommandStep(operation='move',values={'unknown':0.})]),
        AdapterCommand(id='bad',name='Bad',parameters={'value':CommandParameter(min=0.,max=1.,default=.5,unit='m')},steps=[CommandStep(operation='move',values={'base_yaw':'$value'})]),
        AdapterCommand(id='bad',name='Bad',steps=[CommandStep(operation='wait',duration=10)]*7)]
    for command in cases:
        with pytest.raises(ValueError):validate_catalog([command],controls,initial)
    renamed={'J-1':controls['base_yaw']};commands=default_commands(renamed,{'J-1':0.})
    assert validate_catalog(commands,renamed,{'J-1':0.})


def test_documentation_discovery_keeps_unsupported_commands_explicit_and_verifies_evidence(store,monkeypatch):
    original=httpx.AsyncClient
    documented={'id':'rotate_base','name':'Rotate base','vendor_command':'move_base(angle)','documentation_quote':'move_base(angle): sets base angle in radians.',
        'parameters':{'angle':{'min':-.5,'max':.5,'default':0.,'unit':'rad'}},'steps':[{'operation':'move','values':{'base_yaw':'$angle'}}]}
    invented={**documented,'id':'invented','vendor_command':'invented_api(angle)','documentation_quote':'This does not occur in the supplied docs.'}
    sensor={'id':'camera','name':'Read camera','simulation_supported':False,'unsupported_reason':'No camera simulator is configured.','steps':[]}
    def response(req):return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'commands':[documented,invented,sensor]})}}]})
    monkeypatch.setattr('services.ai_orchestrator.llm.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(response),**kwargs))
    LLMRegistry(store).save(ProviderConfiguration(name='Docs model',model='test',base_url='http://model.local/v1'))
    with TestClient(create_app(store)) as client:
        body={'model_id':'demo_arm','name':'Documented virtual adapter','kind':'mock','target':'virtual','configuration_method':'documentation','sdk_version':'2.1','documentation':'move_base(angle): sets base angle in radians. Camera returns an image.'}
        found=client.post('/api/projects/apple_transfer/adapters/discover-commands',json=body)
        assert found.status_code==200,found.text
        commands=found.json()['commands']
        assert commands[0]['simulation_supported'] and not commands[1]['simulation_supported'] and not commands[2]['simulation_supported']
        result=client.post('/api/projects/apple_transfer/adapters/generate',json={**body,'commands':commands})
        assert result.status_code==201,result.text
        bundle=result.json()
        assert bundle['category']=='virtual' and bundle['commands'][0]['vendor_command']=='move_base(angle)'
        assert bundle['commands'][1]['steps']==[] and bundle['commands'][1]['unsupported_reason']
        assert client.post('/api/projects/apple_transfer/adapters/generate',json={**body,'target':'physical','commands':commands}).status_code==422


def test_named_command_api_parameter_validation_and_unavailable_commands(store):
    with TestClient(create_app(store)) as client:
        command={'id':'unsupported','name':'Unsupported','simulation_supported':False,'unsupported_reason':'No simulator implementation','steps':[]}
        bundle=client.post('/api/projects/apple_transfer/adapters/generate',json={'model_id':'demo_arm','name':'Test','kind':'sdk','target':'physical','configuration_method':'custom','commands':[command]}).json()
        client.post(f"/api/adapters/{bundle['id']}/review",json={'expected_hash':bundle['hash']})
        client.post(f"/api/adapters/{bundle['id']}/test")
        session=client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':bundle['id']}).json()
        path=f"/api/controls/{session['id']}/named-command"
        assert client.post(path,json={'command_id':'unsupported'}).status_code==422
        assert client.post(path,json={'command_id':'set_joints','arguments':{'base_yaw':True}}).status_code==422
        assert client.delete('/api/controls/'+session['id']).status_code==200


async def test_physical_documentation_flow_drafts_catalog_and_sdk_with_selected_provider(store,instance,monkeypatch):
    calls=[];original=httpx.AsyncClient
    command={'id':'rotate','name':'Rotate','vendor_command':'rotate(angle)','documentation_quote':'rotate(angle) sets base angle in radians.',
        'parameters':{'angle':{'min':-.5,'max':.5,'default':0.,'unit':'rad'}},'steps':[{'operation':'move','values':{'base_yaw':'$angle'}}]}
    def respond(request):
        body=json.loads(request.content);calls.append(body)
        system=body['messages'][0]['content']
        content=json.dumps({'commands':[command]}) if 'Extract documented robot commands' in system else 'class Transport:\n    def command(self, positions):\n        raise NotImplementedError("Implement and validate vendor transport")\n'
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
    monkeypatch.setattr('services.ai_orchestrator.llm.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
    provider=LLMRegistry(store).save(ProviderConfiguration(name='Docs SDK model',base_url='http://model.local/v1',model='sdk-model'))
    registry=AdapterRegistry(store)
    bundle=await registry.generate(GenerateAdapter(model_id='demo_arm',name='Documented SDK',kind='sdk',target='physical',configuration_method='documentation',sdk_version='3.0',documentation='rotate(angle) sets base angle in radians.',llm_adapter_id=provider['id']),instance['initial_configuration']['actuator_positions'])
    assert len(calls)==2 and all(c['model']=='sdk-model' for c in calls)
    assert bundle['commands'][0]['id']=='rotate' and bundle['commands'][0]['simulation_supported']
    assert 'NotImplementedError' in bundle['sdk_source'] and bundle['live_eligible'] is False
    assert bundle['provenance']['llm_adapter']['adapter_id']==provider['id']
    registry.review(bundle['id'],bundle['hash'])
    assert (await registry.test(bundle['id']))['test_report']['passed']

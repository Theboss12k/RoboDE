import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import httpx
from examples.run_plan import create_plan
from services.api.main import create_app
from services.validation.registry import load_model
from services.planning.definitions import validate_definition
from simulation.scenario_runner.run import EXAMPLES,example_names,load_example,scenario


@pytest.mark.parametrize('name',example_names())
def test_all_examples_use_the_new_task_contract(name):
    definition=load_example(name)
    validate_definition(definition,{t.robot_id for t in definition.tasks if t.robot_id})
    for task in definition.tasks:
        assert task.operation in {'command','grasp','release','verify','llm'}
        assert task.target is None and task.joint_positions is None
        if task.operation=='command':
            assert task.command is not None and task.command.target
            if task.command.type=='MOVE_END_EFFECTOR':assert task.command.position_unit=='m' and task.command.frame
            else:assert task.command.unit in {'rad','m','percent'}


@pytest.mark.parametrize('name',[n for n in example_names() if n!='llm_tasks'])
async def test_rewritten_examples_compile_and_execute_without_modifying_source(store,tmp_path,name):
    before={p.relative_to(store.projects):p.read_bytes() for p in store.projects.rglob('*') if p.is_file()}
    output=tmp_path/'output'
    assert await scenario(example=name,speed=1000,output=output,source_store=store)==0
    run=json.loads((output/'run.json').read_text())
    assert run['status']=='SIMULATION_PASSED' and run['stopped_verified']
    revisions=list((output/'plan/revisions').glob('*/plan.json'));assert len(revisions)==1
    revision=json.loads(revisions[0].read_text());assert revision['definition_id']==load_example(name).id
    assert run['revision_id']==revision['id']
    assert all(t['operation']!='move' for t in revision['atomic_tasks'])
    assert {p.relative_to(store.projects):p.read_bytes() for p in store.projects.rglob('*') if p.is_file()}==before
    if name=='multi_robot':
        assert revision['task_schedule']['pick_a:approach']['start']==revision['task_schedule']['pick_b:approach']['start']
    if name=='multi_effector_pose':
        assert run['robot_states']['gantry_01']['positions']['arm_1_x']==0
        assert run['robot_states']['gantry_01']['positions']['arm_2_x']==pytest.approx(.25,abs=.0005)
    if name=='lift_apple':assert run['frame']['held_objects']['arm_01']=='apple'


def test_cartesian_bundle_matches_the_reusable_model_and_imports(store):
    bundle=json.loads((EXAMPLES/'models/dual_cartesian.robot.json').read_text())
    model=load_model(EXAMPLES/'models/dual_cartesian')
    for key in ('actuators','kinematics','capabilities'):assert bundle[key]==model[key]
    with TestClient(create_app(store)) as client:
        result=client.post('/api/registry/import',json=bundle)
        assert result.status_code==201,result.text
        assert result.json()['planning_supported']


async def test_api_example_creates_and_compiles_current_plan_definition(store):
    app=create_app(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        definition,revision=await create_plan(client,'wave','apple_transfer')
        assert revision['valid'] and revision['definition_id']==definition['id']
        assert all(t['command']['unit']=='rad' for t in definition['tasks'] if t['operation']=='command')
    await app.state.controller.close()


async def test_llm_example_requires_explicit_provider_permission_before_running(store,tmp_path):
    with pytest.raises(ValueError,match='--allow-llm'):
        await scenario(example='llm_tasks',speed=1000,output=tmp_path/'output',source_store=store)
    assert not (tmp_path/'output').exists()


def test_documented_task_and_command_examples_match_registered_contracts(model):
    import re
    from shared.models.domain import PlanDefinition,TaskDefinition
    from shared.models.command import StandardCommand
    from services.commands.standard import resolve_command
    from services.validation.registry import REPOSITORY_ROOT
    multi=load_model(EXAMPLES/'models/dual_cartesian')
    initial=json.loads((EXAMPLES/'models/dual_cartesian.robot.json').read_text())['initial_configuration']['actuator_positions']
    demo_initial=read_demo_initial()
    for name in ('ADAPTERS.md','CONFIGURATION.md','TASK_PIPELINE.md'):
        for raw in re.findall(r'```json\n(.*?)\n```',(REPOSITORY_ROOT/'docs'/name).read_text(),flags=re.S):
            data=json.loads(raw)
            if 'project_id' in data:
                plan=PlanDefinition.model_validate(data);validate_definition(plan,{t.robot_id for t in plan.tasks})
                commands=[t.command for t in plan.tasks if t.command]
            elif 'operation' in data:
                task=TaskDefinition.model_validate(data);commands=[task.command] if task.command else []
            elif 'type' in data:commands=[StandardCommand.model_validate(data)]
            else:continue
            for command in commands:
                selected=multi if command.target=='arm_2_gripper' else model
                resolve_command(selected,initial if selected is multi else demo_initial,command)


def read_demo_initial():
    from services.validation.registry import MODEL_ROOT,read_yaml
    return read_yaml(MODEL_ROOT/'demo_arm/instances/instance.yaml')['initial_configuration']['actuator_positions']


async def test_llm_example_uses_selected_profiles_and_keeps_credentials_out_of_artifacts(store,tmp_path,monkeypatch):
    from services.ai_orchestrator.llm import LLMRegistry,ProviderConfiguration
    import dotenv
    monkeypatch.setattr(dotenv,'load_dotenv',lambda *_:False)
    registry=LLMRegistry(store)
    profile=registry.save(ProviderConfiguration(name='Example provider',base_url='https://example.invalid/v1',model='test',api_key='EXAMPLE_SECRET_NOT_FOR_EXPORT'))
    calls=[]
    def adapter(self,adapter_id=None):
        async def invoke(input,system_prompt=''):
            calls.append((adapter_id,input,system_prompt))
            return {'answer':'A task description' if len(calls)==1 else 'A concise summary','adapter_id':profile['id'],'model':'test'}
        return invoke
    monkeypatch.setattr(LLMRegistry,'adapter',adapter)
    output=tmp_path/'llm-output'
    assert await scenario(example='llm_tasks',speed=1000,output=output,allow_llm=True,source_store=store)==0
    assert len(calls)==2 and 'A task description' in calls[1][1]
    run=json.loads((output/'run.json').read_text());assert run['evidence']['llm']['summarize']['answer']=='A concise summary'
    assert not any('EXAMPLE_SECRET_NOT_FOR_EXPORT' in p.read_text() for p in output.rglob('*') if p.is_file())

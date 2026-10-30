"""Simple planner/converter flow: scope, explicit calls, edits and immutable history."""
import json
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.execution.controller import SimulationController
from services.planning.definitions import validate_definition
from services.ai_orchestrator.two_stage import decompose
from shared.models.domain import PlanDefinition, TaskDefinition
from test_robotics_v2 import AnswerRegistry


async def test_selected_robots_limit_planner_context_and_reject_an_unselected_assignment(store):
    runtime=SimulationController(store)
    try:
        *_,cell,_=await runtime.context('apple_transfer')
        # A second instance is enough to prove the context filter, without changing saved user projects.
        from copy import deepcopy
        cell.instances['other']=deepcopy(cell.instances['arm_01']);cell.instances['other']['instance']['id']='other'
        cell.models['other']=deepcopy(cell.models['arm_01'])
        states={'arm_01':(await runtime.states(cell))['arm_01']}
        states['other']=states['arm_01']
        definition=PlanDefinition(id='scoped',project_id='apple_transfer',name='Scoped',goal='Point',allowed_robot_ids=['arm_01'])
        task=TaskDefinition(id='point',name='Point',operation='command',robot_id='other',binding_status='unresolved')
        registry=AnswerRegistry(store.runtime/'llm',[json.dumps({'status':'ready','tasks':[task.model_dump()]})])
        with pytest.raises(ValueError,match='outside the selected robots'):
            await decompose(registry,definition,cell,states,'snapshot')
        assert [r['id'] for r in json.loads(registry.calls[0][1])['robots']]==['arm_01']
    finally:await runtime.close()


def test_scope_preserves_existing_assignments_and_rejects_unknown_or_duplicate_ids():
    definition=PlanDefinition(id='scope',project_id='p',name='p',allowed_robot_ids=['one'],tasks=[
        TaskDefinition(id='old',name='Old task',operation='command',robot_id='two',binding_status='unresolved')])
    # Scope controls future generation. Selecting robots must never reassign an existing task.
    validate_definition(definition,{'one','two'})
    assert definition.tasks[0].robot_id=='two'
    for invalid in (['one','one'],['missing']):
        definition.allowed_robot_ids=invalid
        with pytest.raises(ValueError,match='distinct robots'):
            validate_definition(definition,{'one','two'})


def test_intent_edit_clears_old_calls_while_manual_call_edits_survive_and_other_plans_are_unchanged(store):
    with TestClient(create_app(store)) as client:
        root='/api/projects/apple_transfer/plan-definitions'
        p=client.post(root,json={'name':'Editable','goal':'Turn shoulder'}).json()
        other=client.post(root,json={'name':'Independent','goal':'Wait'}).json()
        url=f"{root}/{p['id']}"
        task=TaskDefinition(id='turn',name='Turn',intent='Turn shoulder',operation='command',robot_id='arm_01',
            binding_status='unresolved',authored_by='user',function_calls=[{'function':'set_shoulder','arguments':{'value':.2,'unit':'rad'}}])
        def edit(plan,tasks,**extra):
            result=client.put(url,json={**{k:plan[k] for k in ('name','goal','version')},'tasks':tasks,**extra})
            assert result.status_code==200,result.text
            return result.json()
        p=edit(p,[task.model_dump()],allowed_robot_ids=['arm_01'])
        bound=client.post(url+'/bind-commands',json={'version':p['version']}).json()
        assert not bound['errors'];p=bound['definition']
        compiled=client.post(url+'/compile');assert compiled.status_code==201,compiled.text
        revision=compiled.json()
        tasks=p['tasks'];tasks[0]['intent']='Turn shoulder further'
        p=edit(p,tasks)
        assert p['tasks'][0]['function_calls']==[] and p['tasks'][0]['binding_status']=='unresolved'
        tasks=p['tasks'];tasks[0]['intent']='User-edited instruction and calls together';tasks[0]['function_calls']=[{'function':'set_shoulder','arguments':{'value':.3,'unit':'rad'}}]
        p=edit(p,tasks)
        rebound=client.post(url+'/bind-commands',json={'version':p['version']}).json()
        assert not rebound['errors'] and rebound['definition']['tasks'][0]['function_calls'][0]['arguments']['value']==.3
        assert client.get(f"{root}/{other['id']}").json()==other
        assert store.get_plan('apple_transfer',revision['id']).definition_version==revision['definition_version']
        assert client.get(url).json()['allowed_robot_ids']==['arm_01']

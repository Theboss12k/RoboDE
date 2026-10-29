import asyncio
import json
import shutil
import yaml
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.api.storage import fingerprint
from services.execution.controller import SimulationController
from services.planning.definitions import compile_definition
from services.planning.planner import build_plan
from services.ai_orchestrator.providers import TemplateProvider
from shared.models.domain import PlanDefinition,TaskDefinition
from services.validation.registry import ROOT


def test_plan_crud_draft_edit_compile_and_stale_revision(store):
    with TestClient(create_app(store,speed=2000)) as client:
        base='/api/projects/apple_transfer/plan-definitions'
        definition=client.post(base,json={'name':'Apple transfer','goal':'Put the apple in the basket.'}).json()
        assert definition['tasks']==[]
        path=base+'/'+definition['id']
        draft=client.post(path+'/draft',json={'version':1,'goals':[{'id':'goal_a','robot_id':'arm_01','prompt':'Pick up the apple and place it in the basket.'}]}).json()
        assert len(draft['tasks'])==9
        assert all(t['robot_id']=='arm_01' for t in draft['tasks'])
        revision=client.post(path+'/compile').json()
        assert revision['valid'],revision
        assert revision['definition_id']==definition['id']
        assert revision['definition_version']==draft['version']
        changed={k:draft[k] for k in ('name','goal','tasks','version')}
        changed['tasks'][0]['name']='Approach carefully'
        updated=client.put(path,json=changed)
        assert updated.status_code==200
        assert client.put(path,json=changed).status_code==409
        rejected=client.post(f"/api/projects/apple_transfer/plans/{revision['id']}/simulate",json={'fingerprint':revision['fingerprint']})
        assert rejected.status_code==422 and 'stale' in rejected.text
        stored=store.get_plan('apple_transfer',revision['id'])
        assert stored.atomic_tasks[0].name=='Approach object'
        recompiled=client.post(path+'/compile').json()
        assert recompiled['id']!=revision['id']
        assert recompiled['atomic_tasks'][0]['name']=='Approach carefully'
        assert client.delete(path).status_code==200
        assert client.get(base).json()==[]
        assert store.get_plan('apple_transfer',revision['id']).id==revision['id']


async def test_atomic_pick_place_verifies_each_action(store):
    runtime=SimulationController(store,speed=1000)
    project,instance,model,session,state=await runtime.context('apple_transfer')
    legacy=build_plan(project['id'],project['default_prompt'],await TemplateProvider().interpret(project['default_prompt'],session.objects),'Local',model,instance,session.objects,state.positions,'unused')
    definition=store.definition_from_revision(legacy)
    definition.latest_revision_id=None
    store.save_definition(definition)
    snapshot=await runtime.snapshot(project['id'])
    revision=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock')
    assert revision.valid,revision.checks
    store.save_plan(revision,snapshot)
    run=await runtime.execute_registered_plan(revision.id,revision.fingerprint,project['id'])
    await runtime.jobs[run.id]
    assert run.status=='SIMULATION_PASSED',run.logs
    assert len(run.task_statuses)==9
    assert run.evidence['postcondition_passed']
    assert run.definition_id==definition.id and run.revision_id==revision.id
    await runtime.close()


async def test_legacy_migration_preserves_original_artifacts_and_history(store):
    runtime=SimulationController(store)
    project,instance,model,session,state=await runtime.context('apple_transfer')
    snapshot=await runtime.snapshot(project['id'])
    revision=build_plan(project['id'],'Move home.',await TemplateProvider().interpret('Move home.',session.objects),'Local',model,instance,session.objects,state.positions,fingerprint(snapshot))
    folder=store.project_folder(project['id'])/'tasks'/revision.id
    folder.mkdir(parents=True)
    original=revision.model_dump_json(indent=2)
    (folder/'plan.json').write_text(original)
    (folder/'snapshot.json').write_text(json.dumps(snapshot))
    (folder/'generated.py').write_text(revision.code)
    first=store.list_definitions(project['id'])
    second=store.list_definitions(project['id'])
    assert len(first)==len(second)==1
    assert [t.operation for t in first[0].tasks]==['move','verify']
    assert (folder/'plan.json').read_text()==original
    target=folder.parents[1]/'plans'/revision.id/'revisions'/revision.id
    assert (target/'plan.json').read_text()==original
    assert (folder.parents[1]/'migration_backups/v1/tasks'/revision.id/'plan.json').read_text()==original
    assert store.get_plan(project['id'],revision.id).frames==revision.frames
    await runtime.close()


async def test_parallel_atomic_tasks_and_shared_resources_serialize(store):
    source=ROOT/'examples/projects/dual_arm_cell'
    target=store.project_folder('dual_arm_cell')
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('tasks','plans','results','migration_backups'))
    runtime=SimulationController(store,speed=1000)
    *_,session,_=await runtime.context('dual_arm_cell')
    definition=PlanDefinition(id='parallel',project_id='dual_arm_cell',name='Parallel homes',tasks=[
        TaskDefinition(id='a',name='Home A',operation='move',robot_id='arm_01'),
        TaskDefinition(id='b',name='Home B',operation='move',robot_id='arm_02'),
        TaskDefinition(id='c',name='Home A again',operation='move',robot_id='arm_01')])
    store.save_definition(definition)
    snapshot=await runtime.snapshot('dual_arm_cell')
    revision=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock')
    assert revision.task_schedule['a']['start']==revision.task_schedule['b']['start']
    assert revision.task_schedule['c']['start']>revision.task_schedule['a']['end']
    assert 'a' in revision.atomic_tasks[2].dependencies
    store.save_plan(revision,snapshot)
    run=await runtime.execute_registered_plan(revision.id,revision.fingerprint,'dual_arm_cell')
    await runtime.jobs[run.id]
    assert run.status=='SIMULATION_PASSED',run.logs
    await runtime.close()


def test_unknown_robots_cycles_and_configuration_changes_are_rejected(store):
    with TestClient(create_app(store)) as client:
        base='/api/projects/apple_transfer/plan-definitions'
        d=client.post(base,json={'name':'Home'}).json()
        path=base+'/'+d['id']
        task={'id':'home','name':'Home','operation':'move','robot_id':'missing'}
        assert client.put(path,json={'name':'Home','goal':'','version':1,'tasks':[task]}).status_code==422
        task.update(robot_id='arm_01',dependencies=['home'])
        assert client.put(path,json={'name':'Home','goal':'','version':1,'tasks':[task]}).status_code==422
        task['dependencies']=[]
        assert client.put(path,json={'name':'Home','goal':'','version':1,'tasks':[task]}).status_code==200
        revision=client.post(path+'/compile').json()
        client.put('/api/projects/apple_transfer/initial',json={'robot_id':'arm_01','positions':{'base_yaw':.1,'shoulder':.9,'elbow':-1.3,'wrist':.4,'gripper':.08}})
        response=client.post(f"/api/projects/apple_transfer/plans/{revision['id']}/simulate",json={'fingerprint':revision['fingerprint']})
        assert response.status_code==422 and 'stale' in response.text

async def test_generated_tasks_keep_object_and_destination_resources(store):
    runtime=SimulationController(store)
    project,instance,model,session,state=await runtime.context('apple_transfer')
    intent=await TemplateProvider().interpret(project['default_prompt'],session.objects)
    legacy=build_plan(project['id'],project['default_prompt'],intent,'Local',model,instance,session.objects,state.positions,'unused')
    definition=store.definition_from_revision(legacy)
    assert all(t.object_id=='apple' and t.target_id=='basket' for t in definition.tasks)
    await runtime.close()

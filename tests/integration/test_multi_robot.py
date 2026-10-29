import shutil
import pytest
from shared.models.domain import Lifecycle
from services.validation.registry import ROOT
from services.api.storage import fingerprint
from services.execution.controller import SimulationController
from services.planning.workflow import Assignment,build_workflow
from services.ai_orchestrator.providers import TemplateProvider


async def compile_cell(store,dependencies=False):
    shutil.copytree(ROOT/'examples/projects/dual_arm_cell',store.projects/'dual_arm_cell')
    runtime=SimulationController(store,speed=500)
    project,_,_,session,_=await runtime.context('dual_arm_cell')
    assignments=[Assignment.model_validate(a) for a in project.get('default_goals') or project.get('workflow_tasks',[])]
    if dependencies:
        assignments[1].dependencies=['pick_a']
    provider=TemplateProvider()
    intents={a.id:await provider.interpret(a.prompt,session.objects) for a in assignments}
    snapshot=await runtime.snapshot(project['id'])
    plan=build_workflow(project['id'],assignments,intents,provider.name,list(session.instances.values()),session.models,session.objects,await runtime.states(session),fingerprint(snapshot))
    store.save_plan(plan,snapshot)
    return runtime,plan


async def test_parallel_cell_executes_and_verifies_both_robots(store):
    runtime,plan=await compile_cell(store)
    assert plan.valid,plan.checks
    assert plan.workflow_tasks[0].start==plan.workflow_tasks[1].start==0
    assert len(plan.task.steps)==18
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await runtime.jobs[run.id]
    assert run.status==Lifecycle.SIMULATION_PASSED,[l.message for l in run.logs]
    assert run.evidence['tasks']['pick_a']['postcondition_passed']
    assert run.evidence['tasks']['pick_b']['postcondition_passed']
    assert len(run.robot_states)==2
    assert run.stopped_verified
    await runtime.close()


async def test_explicit_dependencies_serialize_robots(store):
    runtime,plan=await compile_cell(store,dependencies=True)
    assert plan.valid
    assert plan.workflow_tasks[1].start>plan.workflow_tasks[0].end
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await runtime.jobs[run.id]
    assert run.status==Lifecycle.SIMULATION_PASSED,[l.message for l in run.logs]
    await runtime.close()


async def test_shared_object_requires_dependency(store):
    runtime,plan=await compile_cell(store)
    session=runtime.sessions[plan.project_id]
    assignments=[Assignment(id='a',robot_id='arm_01',prompt='Move home.'),Assignment(id='b',robot_id='arm_02',prompt='Move home.')]
    provider=TemplateProvider()
    intent=await provider.interpret('Pick up the apple and place it in the basket.',session.objects)
    with pytest.raises(ValueError,match='share an object'):
        build_workflow(plan.project_id,assignments,{'a':intent,'b':intent},provider.name,list(session.instances.values()),session.models,session.objects,await runtime.states(session),plan.fingerprint)
    await runtime.close()


async def test_cancel_stops_all_robots(store):
    runtime,plan=await compile_cell(store)
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    runtime.stop(run.id)
    await runtime.jobs[run.id]
    assert run.status==Lifecycle.CANCELLED
    assert run.stopped_verified
    assert all(s.stopped for s in run.robot_states.values())
    await runtime.close()


async def test_failed_predecessor_does_not_start_dependent_robot(store):
    runtime,plan=await compile_cell(store,dependencies=True)
    second_before=(await runtime.sessions[plan.project_id].adapters['arm_02'].get_state()).positions
    async def ignore(_):pass
    runtime.sessions[plan.project_id].adapters['arm_01'].command=ignore
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await runtime.jobs[run.id]
    assert run.status==Lifecycle.FAILED
    assert 'pick_b' not in run.task_statuses
    assert (await runtime.sessions[plan.project_id].adapters['arm_02'].get_state()).positions==second_before
    await runtime.close()


async def test_final_scene_is_rechecked_after_stop_settling(store):
    from shared.models.domain import Pose
    runtime,plan=await compile_cell(store)
    session=runtime.sessions[plan.project_id]
    original=session.adapters['arm_01'].request_stop
    async def dropped_object():
        await original()
        next(o for o in session.objects if o.id=='apple').position=Pose(x=1,y=1,z=.04)
    session.adapters['arm_01'].request_stop=dropped_object
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await runtime.jobs[run.id]
    assert run.status==Lifecycle.FAILED
    assert run.evidence['final_object_postconditions']['apple'] is False
    await runtime.close()


def test_workflow_cycle_and_unknown_dependencies():
    from services.planning.workflow import ordered_assignments
    with pytest.raises(ValueError,match='cycle'):
        ordered_assignments([Assignment(id='a',robot_id='arm_01',prompt='Move home.',dependencies=['b']),Assignment(id='b',robot_id='arm_02',prompt='Move home.',dependencies=['a'])])
    with pytest.raises(ValueError,match='unknown'):
        ordered_assignments([Assignment(id='a',robot_id='arm_01',prompt='Move home.',dependencies=['missing'])])


def test_same_robot_tasks_serialize():
    from services.planning.workflow import ordered_assignments
    items=ordered_assignments([Assignment(id='a',robot_id='arm_01',prompt='Move home.'),Assignment(id='b',robot_id='arm_01',prompt='Move home.')])
    assert items[1].dependencies==['a']


async def test_inter_robot_collision_rejected_even_when_one_is_idle(store):
    import copy
    from services.planning.workflow import validate_cell
    runtime,plan=await compile_cell(store)
    models=copy.deepcopy(runtime.sessions[plan.project_id].models)
    models['arm_02']['base_pose']=models['arm_01']['base_pose']
    with pytest.raises(ValueError,match='Inter-robot proximity'):
        validate_cell(plan.frames,models,runtime.sessions[plan.project_id].objects)
    await runtime.close()

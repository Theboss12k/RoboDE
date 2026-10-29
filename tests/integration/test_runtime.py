import asyncio
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from shared.models.domain import Lifecycle
from services.api.main import create_app
from services.api.storage import fingerprint
from services.execution.controller import SimulationController
from services.ai_orchestrator.providers import TemplateProvider
from services.planning.planner import build_plan


async def prepared(store, speed=500):
    controller = SimulationController(store,speed=speed)
    project, instance, model, session, state = await controller.context("apple_transfer")
    snapshot = await controller.snapshot("apple_transfer")
    intent = await TemplateProvider().interpret(project["default_prompt"],session.objects)
    plan = build_plan(project["id"], project["default_prompt"], intent, "Local templates", model,instance,session.objects,state.positions,fingerprint(snapshot))
    store.save_plan(plan,snapshot)
    return controller, plan


async def test_complete_pick_place_and_reproducible_artifacts(store):
    controller, plan = await prepared(store)
    assert plan.valid
    run = await controller.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await controller.jobs[run.id]
    assert run.status == Lifecycle.SIMULATION_PASSED
    assert run.evidence["object_inside_target"]
    assert run.evidence["postcondition_passed"]
    assert run.evidence["physics_validated"] is False
    assert run.evidence["hardware_authorized"] is False
    assert run.stopped_verified
    assert [h["to"] for h in run.history] == ["VALIDATING","PLANNING","PLAN_READY","SIMULATING","VERIFYING","SIMULATION_PASSED"]
    assert store.get_run(run.id).status == Lifecycle.SIMULATION_PASSED
    assert (store.project_folder(plan.project_id) / f"plans/{plan.definition_id}/revisions/{plan.id}/snapshot.json").exists()
    assert store.get_plan(plan.project_id,plan.id).frames == plan.frames
    await controller.close()


async def test_stale_state_rejected(store):
    controller, plan = await prepared(store)
    adapter = controller.sessions[plan.project_id].adapter
    state = await adapter.get_state()
    await adapter.command({**state.positions,"base_yaw":.01})
    with pytest.raises(ValueError,match="stale"):
        await controller.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await controller.close()


async def test_exclusive_execution_lease(store):
    controller, plan = await prepared(store,speed=1)
    run = await controller.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    with pytest.raises(ValueError,match="active simulation"):
        await controller.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    controller.stop(run.id)
    await controller.jobs[run.id]
    assert run.status == Lifecycle.CANCELLED
    await controller.close()


async def test_stop_request_and_verified_stop_differ(store):
    controller,plan = await prepared(store,speed=10)
    run = await controller.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    controller.stop(run.id)
    assert run.stop_requested
    assert not run.stopped_verified
    await controller.jobs[run.id]
    assert run.stopped_verified
    assert run.status == Lifecycle.CANCELLED
    assert not run.evidence.get("postcondition_passed",False)
    await controller.close()


async def test_unconfirmed_stop_is_failure(store):
    controller, plan = await prepared(store)
    controller.sessions[plan.project_id].adapter.request_stop = AsyncMock()
    run = await controller.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await controller.jobs[run.id]
    assert run.status == Lifecycle.FAILED
    assert not run.stopped_verified
    assert not run.evidence.get("postcondition_passed",False)
    await controller.close()


async def test_timeout_propagates(store):
    controller, plan = await prepared(store)
    async def slow(_):
        await asyncio.sleep(1)
    controller.command_timeout = .005
    controller.sessions[plan.project_id].adapter.command = slow
    run = await controller.execute_registered_plan(plan.id,plan.fingerprint,plan.project_id)
    await controller.jobs[run.id]
    assert run.status == Lifecycle.TIMED_OUT
    assert any("timed out" in l.message.lower() for l in run.logs)
    await controller.close()


def test_api_workflow_and_hardware_boundary(store):
    with TestClient(create_app(store,speed=500)) as client:
        assert client.get('/api/health').json()['hardware_enabled'] is False
        plan = client.post('/api/projects/apple_transfer/plans',json={'prompt':'Pick up the apple and place it in the basket.'}).json()
        assert plan['valid']
        path = f"/api/projects/apple_transfer/plans/{plan['id']}/simulate"
        assert client.post(path,json={'fingerprint':plan['fingerprint'],'mode':'hardware'}).status_code == 409
        assert client.post(path,json={'fingerprint':plan['fingerprint'],'adapter':'isaac_sim'}).status_code == 409
        response = client.post(path,json={'fingerprint':plan['fingerprint']})
        assert response.status_code == 202
        run_id = response.json()['id']
        import time
        for _ in range(100):
            run = client.get(f'/api/runs/{run_id}').json()
            if run['finished_at']:
                break
            time.sleep(.005)
        assert run['status'] == 'SIMULATION_PASSED'
        assert client.get('/api/projects/apple_transfer').json()['runs'][0]['id'] == run_id


def test_saved_initial_and_sync_do_not_move_actual_state(store):
    with TestClient(create_app(store)) as client:
        before = client.get('/api/projects/apple_transfer').json()
        positions = before['instance']['initial_configuration']['actuator_positions']
        positions['base_yaw'] = .4
        assert client.put('/api/projects/apple_transfer/initial',json={'positions':positions}).status_code == 200
        synced = client.post('/api/projects/apple_transfer/sync').json()
        assert synced['positions']['base_yaw'] == 0
        assert client.get('/api/projects/apple_transfer').json()['instance']['initial_configuration']['actuator_positions']['base_yaw'] == .4
        client.post('/api/projects/apple_transfer/reset')
        assert client.post('/api/projects/apple_transfer/sync').json()['positions']['base_yaw'] == .4


def test_untrusted_browser_and_host_rejected(store):
    with TestClient(create_app(store)) as client:
        assert client.get('/api/health',headers={'origin':'https://attacker.example'}).status_code == 403
        assert client.get('/api/health',headers={'host':'attacker.example'}).status_code == 403


def test_project_instances_are_independent(store):
    project = store.create_project('Second workflow')
    assert project['id'] != 'apple_transfer'
    original = store.load_project('apple_transfer')
    copied = store.load_project(project['id'])
    assert copied[1][0]['robot_model'] == original[1][0]['robot_model']
    assert (store.project_folder(project['id'])/'robots/arm_01/instance.yaml').is_file()


def test_restart_marks_unfinished_run_failed(store):
    from shared.models.domain import Run
    run = Run(id='interrupted',plan_id='old_plan',project_id='apple_transfer')
    store.save_run(run)
    with TestClient(create_app(store)) as client:
        recovered = client.get('/api/runs/interrupted').json()
        assert recovered['status'] == 'FAILED'
        assert recovered['finished_at']
        assert recovered['stopped_verified'] is False
        assert recovered['evidence']['postcondition_passed'] is False


def test_adding_robot_preserves_existing_actual_state(store):
    with TestClient(create_app(store)) as client:
        client.get('/api/projects/apple_transfer')
        runtime=client.app.state.controller
        runtime.sessions['apple_transfer'].adapter.state.positions['base_yaw']=.2
        result=client.post('/api/projects/apple_transfer/robots',json={'id':'arm_02','name':'Second arm','base_pose':{'x':0,'y':1.3,'z':0,'yaw':0}})
        assert result.status_code==201,result.text
        detail=client.get('/api/projects/apple_transfer').json()
        assert len(detail['robots'])==2
        assert detail['robots'][0]['state']['positions']['base_yaw']==.2
        assert detail['robots'][1]['state']['positions']['base_yaw']==0

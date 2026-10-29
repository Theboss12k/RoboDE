import asyncio
import pytest
from services.execution.controller import SimulationController
from services.api.storage import fingerprint
from services.ai_orchestrator.providers import TemplateProvider
from services.planning.planner import build_plan
from shared.models.domain import Lifecycle


async def test_command_acknowledgement_cannot_fake_object_placement(store):
    runtime = SimulationController(store, speed=1000)
    project, instance, model, session, state = await runtime.context('apple_transfer')
    snapshot = await runtime.snapshot(project['id'])
    intent = await TemplateProvider().interpret(project['default_prompt'], session.objects)
    plan = build_plan(project['id'], project['default_prompt'], intent, 'Local templates', model, instance,
                      session.objects, state.positions, fingerprint(snapshot))
    store.save_plan(plan,snapshot)
    original = next(o.position.model_copy() for o in session.objects if o.id == 'apple')
    async def ignored_command(_):
        pass  # Accepted, but actual simulated feedback never moves.
    session.adapter.command = ignored_command
    run = await runtime.execute_registered_plan(plan.id,plan.fingerprint,project['id'])
    await runtime.jobs[run.id]
    assert run.status == Lifecycle.FAILED
    assert not run.evidence.get('postcondition_passed',False)
    assert next(o.position for o in session.objects if o.id == 'apple') == original
    assert any('feedback' in log.message for log in run.logs)
    await runtime.close()

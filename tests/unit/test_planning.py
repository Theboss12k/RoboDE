import math
import pytest
from shared.models.domain import Frame, Pose, TaskStep, WorldObject
from services.ai_orchestrator.providers import TemplateProvider
from services.planning.kinematics import forward, inverse
from services.task_engine.graph import topological_order, can_transition
from services.validation.trajectory import validate_trajectory
from shared.models.domain import Lifecycle


@pytest.mark.parametrize("target", [Pose(x=.34,y=-.16,z=.065), Pose(x=.27,y=.27,z=.26), Pose(x=.2,y=.1,z=.3)])
def test_inverse_forward_consistency(model, target):
    observed = forward(model, inverse(model, target))
    assert math.dist(tuple(target.model_dump().values()), tuple(observed.model_dump().values())) < 1e-8


def test_unreachable(model):
    with pytest.raises(ValueError, match="outside"):
        inverse(model, Pose(x=4, y=0, z=1))


def test_dependency_cycle_and_unknown():
    a = TaskStep(id="a",label="a",operation="move",implementation="test",dependencies=["b"])
    b = TaskStep(id="b",label="b",operation="move",implementation="test",dependencies=["a"])
    with pytest.raises(ValueError, match="cycle"):
        topological_order([a,b])
    with pytest.raises(ValueError, match="unknown"):
        topological_order([a])


def test_dependency_order():
    a = TaskStep(id="a",label="a",operation="move",implementation="test")
    b = TaskStep(id="b",label="b",operation="move",implementation="test",dependencies=["a"])
    assert [s.id for s in topological_order([b,a])] == ["a","b"]


def test_simulation_cannot_authorize_hardware():
    assert not can_transition(Lifecycle.SIMULATION_PASSED, Lifecycle.EXECUTING)
    assert not can_transition(Lifecycle.DRAFT, Lifecycle.COMPLETED)


@pytest.mark.parametrize("prompt", ["Throw the apple into the basket", "Pick up an unknown object", "Don't pick up the apple and place it in the basket", "Pick up the apple and place it in the basket twice", "Pick up the apple and place it in the basket and turn off the camera"])
async def test_unsupported_intents_are_not_approximated(store, prompt):
    objects = store.load_project("apple_transfer")[-1]
    with pytest.raises(ValueError):
        await TemplateProvider().interpret(prompt, objects)


async def test_known_task(store):
    objects = store.load_project("apple_transfer")[-1]
    intent = await TemplateProvider().interpret("Pick up the apple and place it in the basket.", objects)
    assert intent.object_id == "apple"
    assert intent.target_id == "basket"


def test_velocity_violation(model, instance):
    q = instance["initial_configuration"]["actuator_positions"]
    end = {**q, "base_yaw": 1.0}
    with pytest.raises(ValueError, match="velocity"):
        validate_trajectory(model, [Frame(time=0,step_id="a",positions=q,objects={}),Frame(time=.001,step_id="a",positions=end,objects={})], [])


def test_sampled_collision(model, instance):
    q = instance["initial_configuration"]["actuator_positions"]
    obstacle = WorldObject(id="block",name="block",kind="obstacle",position=Pose(x=0,y=0,z=.1),size=Pose(x=.2,y=.2,z=.3))
    with pytest.raises(ValueError, match="collision"):
        validate_trajectory(model,[Frame(time=0,step_id="a",positions=q,objects={}),Frame(time=1,step_id="a",positions=q,objects={})],[obstacle])

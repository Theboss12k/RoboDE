import pytest
from robot_system.registry.models.demo_arm.adapters.mock.adapter import MockAdapter


async def test_mock_contract(model, instance):
    adapter = MockAdapter(model, instance)
    saved = dict(instance["initial_configuration"]["actuator_positions"])
    with pytest.raises(RuntimeError, match="disconnected"):
        await adapter.get_state()
    await adapter.connect()
    assert adapter.capabilities() == {"pick_place", "move_home"}
    await adapter.command({**saved,"base_yaw":.1})
    feedback = await adapter.get_state()
    assert feedback.source == "simulation"
    assert feedback.positions["base_yaw"] == .1
    assert feedback.stopped is False
    assert instance["initial_configuration"]["actuator_positions"] == saved
    await adapter.request_stop()
    assert (await adapter.get_state()).stopped
    await adapter.disconnect()
    with pytest.raises(RuntimeError):
        await adapter.command(saved)


async def test_trajectory_prevalidation_no_partial_motion(model, instance):
    adapter = MockAdapter(model,instance)
    await adapter.connect()
    original = (await adapter.get_state()).positions
    with pytest.raises(ValueError):
        await adapter.execute_trajectory([{**original,"base_yaw":.2},{**original,"elbow":99}])
    assert (await adapter.get_state()).positions == original

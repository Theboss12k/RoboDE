"""In-process kinematic preview. No contact dynamics or hardware communication."""
from shared.models.domain import RobotState
from services.validation.registry import validate_positions


class MockAdapter:
    def __init__(self, model: dict, instance: dict):
        self.model = model
        self.state = RobotState(instance_id=instance["instance"]["id"],
                                positions=dict(instance["initial_configuration"]["actuator_positions"]),
                                source="simulation", connected=False)

    async def connect(self):
        self.state.connected = True

    def capabilities(self):
        return set(self.model["adapters"]["mock"]["capabilities"])

    async def get_state(self):
        if not self.state.connected:
            raise RuntimeError("Adapter is disconnected")
        from shared.models.domain import now
        self.state.measured_at = now()
        return self.state.model_copy(deep=True)

    async def command(self, positions):
        if not self.state.connected:
            raise RuntimeError("Adapter is disconnected")
        validate_positions(self.model, positions)
        self.state.positions = dict(positions)
        self.state.stopped = False

    async def execute_trajectory(self, trajectory):
        for positions in trajectory:
            validate_positions(self.model, positions)
        for positions in trajectory:
            await self.command(positions)

    async def request_stop(self):
        # Instantaneous in-memory stop. A physical adapter must read controller feedback.
        self.state.stopped = True

    async def disconnect(self):
        await self.request_stop()
        self.state.connected = False

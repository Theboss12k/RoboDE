"""Versioned wire contract shared by the Mac runtime and the GPU worker."""
from shared.models.domain import Contract, RobotState, WorldObject,Pose
from pydantic import Field

PROTOCOL = 'robot-ide.isaac.v1'


class WorkerObservation(Contract):
    sequence: int = Field(ge=0)
    states: dict[str, RobotState]
    objects: list[WorldObject]
    measured_at: str
    simulation_time: float = Field(ge=0)
    faults: list[str] = Field(default_factory=list)


class RoomReference(Contract):
    asset_id:str=Field(pattern=r'^[a-f0-9]{64}$')
    name:str=Field(min_length=1,max_length=100)
    metres_per_unit:float=Field(gt=0,le=10000)
    translation:Pose
    yaw_degrees:float=Field(ge=-360,le=360)

class ConnectRequest(Contract):
    load_scene: bool = False
    project_id: str
    robots: list[dict]
    objects: list[WorldObject]
    room:RoomReference|None=None
    # Explicit simulator hand-off only. Ordinary attach/reconnect stays read-only.
    transfer_positions:dict[str,dict[str,float]]|None=None


class StepRequest(Contract):
    sequence: int = Field(ge=1)
    dt: float = Field(gt=0, le=.1)
    positions: dict[str, dict[str, float]]


class ResetRequest(Contract):
    positions: dict[str, dict[str, float]]
    objects: list[WorldObject]


class SceneObjectsRequest(Contract):
    objects: list[WorldObject] = Field(max_length=256)

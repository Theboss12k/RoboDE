"""Versioned robotics contracts shared by setup, planning and execution."""
from typing import Literal
from pydantic import Field, model_validator
from shared.models.contract import Contract


class FunctionCall(Contract):
    function: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


class SceneImage(Contract):
    snapshot_id: str
    captured_at: str
    mime_type: Literal['image/png', 'image/jpeg']
    data_base64: str = Field(max_length=8_000_000)


class RoleSettings(Contract):
    setup_adapter_id: str | None = None
    planner_adapter_id: str | None = None
    binding_adapter_id: str | None = None
    vision_enabled: bool = False


class ActuatorFunction(Contract):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')
    vendor_method: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]*$')
    argument: str = Field(default='value', pattern=r'^[a-zA-Z][a-zA-Z0-9_]*$')
    mode: Literal['position', 'velocity'] = 'position'
    unit: Literal['rad', 'deg', 'm', 'mm', 'rad/s', 'deg/s', 'm/s', 'mm/s'] = 'rad'
    minimum: float
    maximum: float
    documentation_quote: str = Field(min_length=1, max_length=2000)
    write_style: Literal['single', 'joint_vector'] = 'single'
    vendor_joint: str = ''

    @model_validator(mode='after')
    def bounds(self):
        if self.minimum >= self.maximum:
            raise ValueError('Function minimum must be below maximum')
        if (self.mode == 'velocity') != self.unit.endswith('/s'):
            raise ValueError('Control mode and unit must agree')
        return self


class DriverDraft(Contract):
    name: str = Field(min_length=1, max_length=120)
    category: Literal['physical', 'virtual']
    sdk_version: str = Field(min_length=1, max_length=100)
    documentation: str = Field(min_length=1, max_length=60000)
    source_code: str = Field(default='', max_length=60000)
    functions: list[ActuatorFunction] = Field(default_factory=list, max_length=128)
    feedback_method: str = Field(default='', pattern=r'^(?:[a-zA-Z][a-zA-Z0-9_]*)?$')
    stop_method: str = Field(default='', pattern=r'^(?:[a-zA-Z][a-zA-Z0-9_]*)?$')
    disconnect_method: str = Field(default='', pattern=r'^(?:[a-zA-Z][a-zA-Z0-9_]*)?$')
    watchdog_method: str = Field(default='', pattern=r'^(?:[a-zA-Z][a-zA-Z0-9_]*)?$')
    watchdog_timeout_seconds: float = Field(default=2,ge=.1,le=3)
    sdk_module: str = Field(default='', pattern=r'^(?:[a-zA-Z][a-zA-Z0-9_.]*)?$')
    client_factory: str = Field(default='Client', pattern=r'^[a-zA-Z][a-zA-Z0-9_]*$')
    connection: dict[str, str | int | float] = Field(default_factory=dict)


class JointBinding(Contract):
    joint_id: str
    function_id: str | None = None
    alias: str = ''
    role: Literal['independent', 'passive', 'coupled'] = 'independent'
    scale: float = 1
    offset: float = 0
    coupled_to: str | None = None
    multiplier: float = 1


class Mobility(Contract):
    classification: Literal['STATIONARY', 'MOVING', 'BOTH'] = 'STATIONARY'
    priority: Literal['arm_first', 'base_first'] = 'arm_first'
    left_wheel: str = ''
    right_wheel: str = ''
    wheel_radius_m: float = Field(default=.05, gt=0)
    track_width_m: float = Field(default=.3, gt=0)
    footprint: list[list[float]] = Field(default_factory=list)
    max_linear_m_s: float = Field(default=.2, gt=0, le=5)
    max_angular_rad_s: float = Field(default=.5, gt=0, le=10)
    map_frame: str = 'map'
    odom_frame: str = 'odom'
    base_frame: str = 'base_link'
    transit_positions: dict[str, float] = Field(default_factory=dict)
    navigation_bounds: list[float] | None = None


class RobotBinding(Contract):
    schema_version: int = 2
    physical_description: str = Field(default="",max_length=8000)
    model_id: str
    driver_id: str
    joints: list[JointBinding]
    end_effectors: dict[str, dict] = Field(default_factory=dict)
    mobility: Mobility = Field(default_factory=Mobility)
    workspace_bounds: list[float] | None = None
    reviewed: bool = False
    grasp_enabled: bool = False
    grasp_contacts: dict[str,list[str]] = Field(default_factory=dict)


class ValidationFinding(Contract):
    code: str
    message: str
    task_id: str | None = None
    robot_id: str | None = None
    position: list[float] | None = None
    time: float | None = None


class ValidationReport(Contract):
    status: Literal['passed', 'failed', 'incomplete']
    coverage: list[str] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)
    worker_revision: str | None = None
    hardware_validated: bool = False

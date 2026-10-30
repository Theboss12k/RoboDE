"""Common, serializable contracts. All world coordinates are metres, Z up."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from pydantic import Field
from shared.models.contract import Contract


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Pose(Contract):
    x: float
    y: float
    z: float


class MeshReference(Contract):
    asset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    format: Literal["glb", "gltf", "obj", "stl"]
    filename: str = Field(min_length=1, max_length=180)
    up_axis: Literal["Y", "Z"] = "Y"


class WorldObject(Contract):
    id: str
    name: str
    kind: Literal["object", "region", "obstacle"]
    position: Pose
    size: Pose
    mass_kg: float = Field(default=0, ge=0)
    mesh: MeshReference | None = None


class RobotState(Contract):
    instance_id: str
    positions: dict[str, float]
    source: Literal["simulation", "hardware"]
    measured_at: str = Field(default_factory=now)
    stopped: bool = True
    connected: bool = True
    velocities: dict[str,float] = Field(default_factory=dict)
    attachments: list[str] = Field(default_factory=list)
    attachment_tools: dict[str,str] = Field(default_factory=dict)
    attachment_source: Literal["unavailable","kinematic_preview","simulation_contact","simulation_observed_motion","hardware_sensor"] = "unavailable"
    base_pose: dict[str,float] | None = None


class Lifecycle(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    SIMULATING = "SIMULATING"
    SIMULATION_PASSED = "SIMULATION_PASSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class TaskStep(Contract):
    id: str
    label: str
    operation: Literal["move", "grasp", "release", "verify", "llm", "command"]
    implementation: str
    dependencies: list[str] = Field(default_factory=list)
    target: Pose | None = None
    object_id: str | None = None
    status: str = "pending"
    robot_id: str | None = None


class TaskSpec(Contract):
    id: str
    description: str
    robot_id: str
    template: Literal["pick_place", "move_home", "multi_robot"]
    template_version: str = "1.0.0"
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    required_capabilities: list[str]
    object_id: str | None = None
    target_id: str | None = None
    success_condition: str
    steps: list[TaskStep]
    provider: str


class Check(Contract):
    id: str
    label: str
    status: Literal["passed", "failed", "warning"]
    message: str


class Frame(Contract):
    time: float
    step_id: str
    positions: dict[str, float]
    objects: dict[str, Pose]
    held_object: str | None = None
    robot_positions: dict[str, dict[str, float]] = Field(default_factory=dict)
    held_objects: dict[str, str | None] = Field(default_factory=dict)
    active_steps: dict[str, str] = Field(default_factory=dict)
    base_poses: dict[str,dict[str,float]] = Field(default_factory=dict)
    held_tools: dict[str,str | None] = Field(default_factory=dict)
    pending_grasps: dict[str,dict] = Field(default_factory=dict)


class WorkflowTask(Contract):
    id: str
    robot_id: str
    dependencies: list[str]
    start: float
    end: float
    task: TaskSpec
    final_positions: dict[str, float]


from shared.models.command import StandardCommand
from shared.models.robotics import FunctionCall, RoleSettings, ValidationReport


class TaskDefinition(Contract):
    """One editable task; trajectory samples are compiler implementation details."""
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_:-]{0,119}$")
    name: str = Field(min_length=1, max_length=120)
    operation: Literal["move", "grasp", "release", "verify", "llm", "command"]
    robot_id: str = Field(default="", max_length=80)
    dependencies: list[str] = Field(default_factory=list)
    target: Pose | None = None
    joint_positions: dict[str, float] | None = None
    object_id: str | None = None
    target_id: str | None = None
    command: StandardCommand | None = None
    placement: Literal['inside','on_surface'] = 'inside'
    llm_adapter_id: str | None = None
    llm_input: str = Field(default='', max_length=32000)
    llm_system_prompt: str = Field(default='', max_length=16000)
    intent: str = Field(default='', max_length=4000)
    function_calls: list[FunctionCall] = Field(default_factory=list, max_length=128)
    binding_status: Literal['legacy', 'unresolved', 'resolved'] = 'legacy'
    binding_fingerprint: str | None = None
    authored_by: Literal['user', 'planner', 'legacy'] = 'legacy'
    completion_condition: str = Field(default='', max_length=1000)
    duration_seconds: float | None = Field(default=None, gt=0, le=3600)
    repeat_count: int = Field(default=1, ge=1, le=100)
    binding_error: str | None = None


class InferenceEvidence(Contract):
    """Provenance of one planner/binder model call; never contains prompts, answers or credentials."""
    stage: Literal['planner', 'binder']
    task_id: str | None = None
    adapter_id: str | None = None
    adapter_version: int | None = None
    model: str | None = None
    provider_host: str | None = None
    duration_seconds: float | None = None
    usage: dict[str, float] = Field(default_factory=dict)
    finish_reason: str | None = None
    recorded_at: str = Field(default_factory=now)


class PlanDefinition(Contract):
    allowed_robot_ids: list[str] = Field(default_factory=list,max_length=64)
    id: str
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(default="", max_length=4000)
    tasks: list[TaskDefinition] = Field(default_factory=list, max_length=144)
    version: int = Field(default=1, ge=1)
    latest_revision_id: str | None = None
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    schema_version: int = 2
    planning_status: Literal['draft', 'needs_clarification', 'unsupported', 'tasks_ready', 'commands_ready'] = 'draft'
    clarification_questions: list[str] = Field(default_factory=list)
    planning_error: str | None = None
    role_settings: RoleSettings = Field(default_factory=RoleSettings)
    scene_snapshot_id: str | None = None
    inference_evidence: list[InferenceEvidence] = Field(default_factory=list, max_length=200)


class Plan(Contract):
    id: str
    project_id: str
    task: TaskSpec
    checks: list[Check]
    frames: list[Frame]
    code: str
    duration: float
    valid: bool
    fingerprint: str
    created_at: str = Field(default_factory=now)
    adapter: Literal["mock", "isaac_sim"] = "mock"
    workflow_tasks: list[WorkflowTask] = Field(default_factory=list)
    definition_id: str | None = None
    definition_version: int | None = None
    atomic_tasks: list[TaskDefinition] = Field(default_factory=list)
    task_schedule: dict[str, dict[str, float]] = Field(default_factory=dict)
    validation_report: ValidationReport | None = None
    motion_manifest: dict = Field(default_factory=dict)


class Log(Contract):
    timestamp: str = Field(default_factory=now)
    level: Literal["info", "success", "warning", "error"]
    message: str
    step_id: str | None = None


class Run(Contract):
    id: str
    plan_id: str
    project_id: str
    mode: Literal["simulation", "physical"] = "simulation"
    adapter: str = "mock"
    status: Lifecycle = Lifecycle.DRAFT
    progress: float = 0
    elapsed: float = 0
    current_step: str | None = None
    stop_requested: bool = False
    stopped_verified: bool = False
    started_at: str = Field(default_factory=now)
    finished_at: str | None = None
    logs: list[Log] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    frame: Frame | None = None
    history: list[dict] = Field(default_factory=list)
    robot_states: dict[str, RobotState] = Field(default_factory=dict)
    step_statuses: dict[str, str] = Field(default_factory=dict)
    task_statuses: dict[str, str] = Field(default_factory=dict)
    definition_id: str | None = None
    revision_id: str | None = None

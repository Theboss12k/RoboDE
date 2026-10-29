export type Pose = { x: number; y: number; z: number };
export type WorldObject = {
  id: string;
  name: string;
  kind: "object" | "region" | "obstacle";
  position: Pose;
  size: Pose;
  mass_kg: number;
  mesh?: {
    asset_id: string;
    format: "glb" | "gltf" | "obj" | "stl";
    filename: string;
    up_axis: "Y" | "Z";
  } | null;
};
export type RobotState = {
  instance_id: string;
  positions: Record<string, number>;
  source: string;
  measured_at: string;
  stopped: boolean;
  connected: boolean;
};
export type Step = {
  robot_id: string | null;
  id: string;
  label: string;
  operation: string;
  implementation: string;
  dependencies: string[];
  target: Pose | null;
  object_id: string | null;
};
export type Check = {
  id: string;
  label: string;
  status: "passed" | "failed" | "warning";
  message: string;
};
export type Frame = {
  robot_positions: Record<string, Record<string, number>>;
  active_steps: Record<string, string>;
  held_objects: Record<string, string | null>;
  time: number;
  step_id: string;
  positions: Record<string, number>;
  objects: Record<string, Pose>;
  held_object: string | null;
};
export type Plan = {
  definition_id: string | null;
  definition_version: number | null;
  atomic_tasks: TaskDefinition[];
  task_schedule: Record<string, { start: number; end: number }>;
  adapter: "mock" | "isaac_sim";
  workflow_tasks: {
    id: string;
    robot_id: string;
    start: number;
    end: number;
    dependencies: string[];
  }[];
  id: string;
  project_id: string;
  task: {
    id: string;
    description: string;
    robot_id: string;
    template: string;
    success_condition: string;
    steps: Step[];
    provider: string;
  };
  checks: Check[];
  frames: Frame[];
  code: string;
  duration: number;
  valid: boolean;
  fingerprint: string;
  created_at: string;
};
export type Run = {
  robot_states: Record<string, RobotState>;
  step_statuses: Record<string, string>;
  task_statuses: Record<string, string>;
  id: string;
  plan_id: string;
  project_id: string;
  adapter: string;
  status: string;
  progress: number;
  elapsed: number;
  current_step: string | null;
  stop_requested: boolean;
  stopped_verified: boolean;
  started_at: string;
  finished_at: string | null;
  logs: {
    timestamp: string;
    level: string;
    message: string;
    step_id?: string;
  }[];
  evidence: Record<string, unknown>;
  frame: Frame | null;
  history: { from: string; to: string; timestamp: string }[];
};
export type Project = {
  default_goals?: Assignment[];
  workflow_tasks?: Assignment[];
  id: string;
  name: string;
  description: string;
  robots: string[];
  environment: string;
  default_prompt: string;
};
export type Instance = {
  control_adapter?: {adapter_id:string; category:"physical"|"virtual"; adapter_hash?:string|null};
  base_pose?: { x: number; y: number; z: number; yaw: number };
  instance: { id: string; name: string };
  robot_model: { id: string; version: string };
  initial_configuration: {
    actuator_positions: Record<string, number>;
    position_unit: string;
  };
};
export type Model = {
  planning_supported?: boolean;
  imported?: boolean;
  source_import?: { format: string; filename: string; sha256: string; warnings: string[] };
  initial_configuration?: Instance["initial_configuration"];
  robot: {
    id: string;
    name: string;
    manufacturer: string;
    family: string;
    type: string;
    version: string;
    description: string;
  };
  actuators: {
    actuators: Record<
      string,
      {
        type: string;
        min: number;
        max: number;
        velocity: number;
        acceleration: number;
        unit: string;
      }
    >;
  };
  kinematics: {
    joints?: {
      parent: string;
      child: string;
      actuator?: string;
      type: string;
      axis?: string;
      axis_vector?: [number, number, number];
      origin?: { xyz?: number[]; rpy?: number[] };
    }[];
    solver: string;
    world_frame?: string;
    end_effectors?: Record<
      string,
      { link: string; xyz?: number[]; rpy?: number[] }
    >;
    links: { base_height: number; upper_arm: number; forearm: number };
  };
  capabilities: {
    operations: string[];
    payload_kg: number;
    end_effector: string;
    components?: Record<
      string,
      { actuator: string; closed: number; open: number }
    >;
  };
  adapters: Record<
    string,
    {
      available: boolean;
      environment: string;
      control_schemes: string[];
      unavailable_reason?: string;
    }
  >;
};
export type ProjectDetail = {
  plan_definitions: PlanDefinition[];
  fingerprint: string | null;
  environment_connected: boolean;
  robots: CellRobot[];
  adapter: "mock" | "isaac_sim";
  worker: Record<string, unknown> | null;
  project: Project;
  instance: Instance;
  model: Model;
  objects: WorldObject[];
  state: RobotState;
  held_object: string | null;
  runs: {
    id: string;
    status: string;
    started_at: string;
    definition_id: string;
    revision_id: string;
  }[];
  plans: { id: string; description: string; valid: boolean }[];
  active_run: string | null;
};
export type Health = {
  cloud_session?: boolean;
  status: string;
  version: string;
  provider: string;
  simulation: string;
  hardware_enabled: boolean;
  isaac_sim_connected: boolean;
};

export type Assignment = {
  id: string;
  robot_id: string;
  prompt: string;
  dependencies: string[];
};
export type CellRobot = { instance: Instance; model: Model; state: RobotState };

export type StandardCommand = {
  type: "SET_ACTUATOR" | "SET_COMPONENT" | "MOVE_END_EFFECTOR";
  target: string;
  value?: number | null;
  unit?: "rad" | "m" | "percent" | null;
  position?: [number, number, number] | null;
  position_unit?: "m" | null;
  orientation_rpy?: [number, number, number] | null;
  orientation_unit?: "rad" | null;
  frame?: string | null;
};
export type TaskDefinition = {
  placement?: "inside" | "on_surface";
  command?: StandardCommand | null;
  llm_adapter_id?: string | null;
  llm_input?: string;
  llm_system_prompt?: string;
  id: string;
  name: string;
  operation: "move" | "grasp" | "release" | "verify" | "llm" | "command";
  robot_id: string;
  dependencies: string[];
  target: Pose | null;
  joint_positions: Record<string, number> | null;
  object_id: string | null;
  target_id: string | null;
};
export type PlanDefinition = {
  id: string;
  project_id: string;
  name: string;
  goal: string;
  tasks: TaskDefinition[];
  version: number;
  latest_revision_id: string | null;
  created_at: string;
  updated_at: string;
};
export type AdapterBundle = {
  configuration_method?: "documentation" | "custom" | "template";
  commands?: AdapterCommand[];
  command_tests?: CommandTest[];
  id: string;
  name: string;
  model_id: string;
  model_version: string;
  kind: "sdk" | "ros2" | "mock" | "isaac_sim";
  category: "physical" | "virtual";
  controls: Model["actuators"]["actuators"];
  joint_mapping: Record<string, string>;
  connection: Record<string, string>;
  sdk_version: string;
  documentation: string;
  translation: string;
  adapter_code: string;
  sdk_source: string;
  contract_tests: string;
  hash: string;
  reviewed_hash: string | null;
  validation_status: string;
  test_report: {
    passed: boolean;
    checks: string[];
    scope: string;
    hardware_validated: boolean;
  } | null;
  live_eligible: boolean;
  provenance: Record<string, unknown>;
};
export type ControlSession = {
  command_run?: CommandTest | null;
  id: string;
  project_id: string;
  robot_id: string;
  adapter_id: string;
  mode: "test" | "environment" | "live";
  category: string;
  feedback: RobotState & {
    translated_command?: Record<string, number>;
    device_id?: string;
    ready?: boolean;
  };
  stop_requested: boolean;
  stopped_verified: boolean;
  connection_validated: boolean;
  armed: boolean;
  expires_in: number;
};

export type ConnectionProfile = {
  id: string;
  name: string;
  adapter_id: string;
  adapter_hash: string;
  connection: Record<string, string>;
  updated_at: string;
};

export type ModelAsset = {
  id: string;
  filename: string;
  format: "glb" | "gltf" | "obj" | "stl";
  sha256: string;
  byte_length: number;
};

export type LLMAdapter = {
  id: string;
  name: string;
  protocol: "chat_completions" | "python_function";
  base_url: string;
  model: string;
  source_code?: string;
  timeout_seconds: number;
  max_tokens: number;
  api_key_env: string;
  has_api_key: boolean;
  version: number;
};
export type LLMConfiguration = {
  default_id: string | null;
  adapters: LLMAdapter[];
};

export type RobotWorkspace = {
  robot_id: string;
  name: string;
  available: boolean;
  reason: string | null;
  points: [number, number, number][];
  bounds: {
    min: [number, number, number];
    max: [number, number, number];
  } | null;
  sample_count: number;
  units: "m";
  frame: "world";
  scope: string;
};
export type WorkspaceOverlay = RobotWorkspace & { color: string };

export type AdapterCommand = {
  id: string;
  name: string;
  description: string;
  vendor_command: string;
  documentation_quote?: string;
  parameters: Record<
    string,
    {
      min: number;
      max: number;
      default: number;
      unit: string;
      description: string;
    }
  >;
  steps: {
    operation: "move" | "increment" | "gripper" | "wait" | "feedback" | "stop";
    values: Record<string, number | string>;
    duration: number;
  }[];
  simulation_supported: boolean;
  unsupported_reason: string;
};
export type CommandTest = {
  id: string;
  command_id: string;
  status: "running" | "passed" | "failed" | "cancelled";
  progress: number;
  current_step: number;
  arguments: Record<string, number>;
  scope: string;
  error: string | null;
  stopped_verified?: boolean;
  started_at: string;
  finished_at: string | null;
  trace: { step: number; feedback: ControlSession["feedback"] }[];
};

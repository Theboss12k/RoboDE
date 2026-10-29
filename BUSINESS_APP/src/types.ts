import type { CellRobot, WorldObject, Run } from "../../SERVER_CLIENT/client/src/types";
export type Project = { id: string; name: string; description: string };
export type Asset = {
  id: string;
  planning_id: string | null;
  name: string;
  kind: string;
  position: { x: number; y: number; z: number };
  size: { x: number; y: number; z: number };
  source: string;
  read_only: boolean;
  prim_path?: string;
  category?: string;
};
export type Command = {
  id: string;
  instruction: string;
  robot_name: string;
  robot_id: string;
  status: string;
  duration: number;
  steps: { id: string; name: string }[];
  checks: { status: string; message: string }[];
  run_id: string | null;
};
export type Workspace = {
  cloud_session?: boolean;
  project: Project;
  connected: boolean;
  backend: string;
  source: string;
  robots: CellRobot[];
  objects: WorldObject[];
  assets: Asset[];
  inventory_scope: string;
  observed_at: string;
  active_run: string | null;
  commands: Command[];
  can_deploy_room: boolean;
  scope: string;
};
export type Progress = Pick<
  Run,
  | "id"
  | "status"
  | "progress"
  | "elapsed"
  | "current_step"
  | "stop_requested"
  | "stopped_verified"
  | "finished_at"
  | "robot_states"
  | "frame"
  | "task_statuses"
  | "logs"
>;
export type Room = {
  id: string;
  name: string;
  status: string;
  photos: number;
  stage: string;
  error?: string | null;
  sha256?: string;
  alignment?: {
    metres_per_unit: number;
    translation: { x: number; y: number; z: number };
    yaw_degrees: number;
    assets: WorldObject[];
  };
};

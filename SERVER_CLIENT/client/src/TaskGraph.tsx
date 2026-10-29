import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Handle,
  Position,
  type NodeProps,
  type Node,
  type Edge,
} from "@xyflow/react";
import {
  Check,
  Circle,
  Grip,
  MoveUpRight,
  ScanLine,
  Hand,
  PackageOpen,
  Sparkles,
} from "lucide-react";
import type { Plan, Run, Step } from "./types";
import "@xyflow/react/dist/style.css";
type TaskNode = Node<
  { step: Step; index: number; state: string; selectedStep: boolean },
  "task"
>;
function TaskCard({ data }: NodeProps<TaskNode>) {
  const Icon =
    data.step.operation === "llm"
      ? Sparkles
      : data.step.operation === "grasp"
        ? Hand
        : data.step.operation === "release"
          ? PackageOpen
          : data.step.operation === "verify"
            ? ScanLine
            : MoveUpRight;
  return (
    <div
      className={`task-node ${data.state} ${data.selectedStep ? "chosen" : ""}`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="node-top">
        <span>
          {String(data.index + 1).padStart(2, "0")} /{" "}
          {data.step.robot_id || data.step.operation}
        </span>
        {data.state === "done" ? (
          <Check size={12} />
        ) : data.state === "running" ? (
          <span className="pulse-dot" />
        ) : (
          <Circle size={9} />
        )}
      </div>
      <strong>
        <Icon size={14} />
        {data.step.label}
      </strong>
      <small>
        {data.state === "running"
          ? "Executing"
          : data.state === "done"
            ? "Task complete"
            : "Ready to simulate"}
      </small>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { task: TaskCard };
export default function TaskGraph({
  plan,
  run,
  selected,
  onSelect,
}: {
  plan: Plan | null;
  run: Run | null;
  selected: string | null;
  onSelect: (step: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    if (!plan) return { nodes: [], edges: [] };
    const matchingRun = run?.plan_id === plan.id ? run : null;
    const current = plan.task.steps.findIndex(
      (s) => s.id === matchingRun?.current_step,
    );
    const lanes = [
      ...new Set(plan.task.steps.map((s) => s.robot_id ?? "robot")),
    ];
    const columns: Record<string, number> = {};
    const visiting = new Set<string>();
    const level = (id: string): number => {
      if (id in columns) return columns[id];
      if (visiting.has(id)) return 0;
      visiting.add(id);
      const step = plan.task.steps.find((s) => s.id === id);
      const next = Math.max(-1, ...(step?.dependencies ?? []).map(level)) + 1;
      visiting.delete(id);
      columns[id] = next;
      return next;
    };
    const laneEnd: Record<string, number> = {};
    const nodes: TaskNode[] = plan.task.steps.map((step, index) => {
      const lane = step.robot_id ?? "robot";
      const column = Math.max(level(step.id), (laneEnd[lane] ?? -1) + 1);
      laneEnd[lane] = column;
      return {
        id: step.id,
        type: "task",
        position: { x: column * 175, y: lanes.indexOf(lane) * 135 },
        data: {
          step,
          index,
          state:
            matchingRun?.step_statuses?.[step.id] === "done" ||
            matchingRun?.status === "SIMULATION_PASSED" ||
            (!plan.workflow_tasks.length &&
              !plan.atomic_tasks?.length &&
              current > index)
              ? "done"
              : (matchingRun?.step_statuses?.[step.id] === "running" ||
                    current === index) &&
                  !matchingRun?.finished_at
                ? "running"
                : "pending",
          selectedStep: selected === step.id,
        },
      };
    });
    const edges: Edge[] = plan.task.steps.flatMap((step) =>
      step.dependencies.map((dep) => ({
        id: `${dep}-${step.id}`,
        source: dep,
        target: step.id,
        type: "smoothstep",
        animated:
          !matchingRun?.finished_at && step.id === matchingRun?.current_step,
        style: { stroke: "#4b6285", strokeWidth: 1.4 },
      })),
    );
    return { nodes, edges };
  }, [plan, run, selected]);
  if (!plan)
    return (
      <div className="empty-state graph-empty">
        <Grip size={26} />
        <p>Your workflow starts with a task.</p>
        <span>
          Describe an operation to generate its graph and implementation.
        </span>
      </div>
    );
  return (
    <ReactFlow
      key={plan.id}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
      minZoom={0.15}
      maxZoom={1.8}
      nodesDraggable={false}
      nodesConnectable={false}
      onNodeClick={(_, node) => onSelect(node.id)}
    >
      <Background color="#273347" gap={18} size={1} />
    </ReactFlow>
  );
}

import PhysicalExecution from "./PhysicalExecution";
import PlanningPipeline, { TaskCommandEditor, type Validation } from "./PlanningPipeline";
import StandardTaskEditor from "./StandardTaskEditor";
import { useEffect, useState, lazy, Suspense } from "react";
import {
  Plus,
  Trash2,
  Save,
  Sparkles,
  Check,
  GitBranch,
  Code2,
  Box,
  History,
  ArrowRight,
  Square,
  Download,
} from "lucide-react";
import type {
  Assignment,
  Plan,
  PlanDefinition,
  ProjectDetail,
  Run,
  TaskDefinition,
  LLMConfiguration,
} from "./types";
import TaskGraph from "./TaskGraph";
import Scene from "./Scene";
import { useRobotWorkspace } from "./RobotWorkspace";
import { download } from "./api";
const CodeView = lazy(() => import("./CodeView"));
export type PlanTab = "tasks" | "simulation" | "code" | "history";

export default function PlanWorkspace({
  detail,
  llm,
  onRefine,
  draft,
  revision,
  run,
  selected,
  tab,
  busy,
  dirty,
  onTab,
  onSelect,
  onChange,
  onSave,
  onDraft,
  onValidate,
  validation,
  onSaved,
  onDecompose,
  onBind,
  onPhysicalRun,
  onRefresh,
  onConfigureAI,
  onOpenControls,
  activity,
  onSimulate,
  onStop,
  onRun,
  onNew,
  onArchive,
}: {
  detail: ProjectDetail;
  llm: LLMConfiguration;
  onRefine: (taskId: string, instruction: string) => void;
  draft: PlanDefinition | null;
  revision: Plan | null;
  run: Run | null;
  selected: string | null;
  tab: PlanTab;
  busy: boolean;
  dirty: boolean;
  onTab: (t: PlanTab) => void;
  onSelect: (id: string) => void;
  onChange: (p: PlanDefinition) => void;
  onSave: () => void;
  onDraft: (goals: Assignment[], adapter_id?: string) => void;
  onValidate: () => void;
  validation: Validation | null;
  onSaved: (p: PlanDefinition) => void;
  onDecompose: (clarifications: Record<string,string>, replace: boolean, image?: unknown) => void;
  onBind: () => void;
  onPhysicalRun: (run:Run) => void;
  onRefresh: () => void;
  onConfigureAI: () => void;
  onOpenControls: () => void;
  activity?: string | null;
  onSimulate: () => void;
  onStop: () => void;
  onRun: (id: string) => void;
  onNew: () => void;
  onArchive: () => void;
}) {
  const reachability = useRobotWorkspace(detail);
  const [goalAdapter, setGoalAdapter] = useState("");
  const [refinement, setRefinement] = useState("");
  useEffect(() => setRefinement(""), [selected]);
  const [goals, setGoals] = useState<Assignment[]>([]);
  const [showGoals, setShowGoals] = useState(false);
  const [allRuns, setAllRuns] = useState(false);
  const [preview, setPreview] = useState<number | null>(null);
  useEffect(() => {
    setGoals(
      detail.project.default_goals ?? detail.project.workflow_tasks ?? [
        {
          id: "goal_1",
          robot_id: detail.robots[0]?.instance.instance.id??"",
          prompt: draft?.goal || detail.project.default_prompt,
          dependencies: [],
        },
      ],
    );
    setShowGoals(false);
    setPreview(null);
  }, [draft?.id, detail.project.id]);
  useEffect(() => { setGoals(current=>current.length===1?[{...current[0],prompt:draft?.goal??""}]:current); }, [draft?.goal]);
  useEffect(() => setPreview(null), [run?.id, revision?.id]);
  useEffect(() => {
    if (draft?.tasks.length) setShowGoals(false);
  }, [draft?.id, draft?.tasks.length]);
  const task = draft?.tasks.find((t) => t.id === selected);
  const stale =
    dirty ||
    revision?.definition_version !== draft?.version ||
    revision?.fingerprint !== detail.fingerprint ||
    !detail.environment_connected;
  const running = !!run && !run.finished_at;
  const setTask = (next: TaskDefinition) =>
    draft &&
    onChange({
      ...draft,
      tasks: draft.tasks.map((t) => (t.id === next.id ? next : t)),
    });
  const frame =
    preview !== null && revision
      ? revision.frames.reduce(
          (a, b) =>
            Math.abs(b.time - preview) < Math.abs(a.time - preview) ? b : a,
          revision.frames[0],
        )
      : run?.plan_id === revision?.id
        ? (run?.frame ?? null)
        : null;
  const primary = detail.robots[0];
  const graph = draft
    ? ({
        ...revision,
        id: revision?.id ?? draft.id,
        workflow_tasks: revision?.workflow_tasks ?? [],
        task: {
          ...revision?.task,
          steps: draft.tasks.map((t) => ({
            ...t,
            label: t.name,
            dependencies:
              revision?.definition_version === draft.version && !dirty
                ? (revision.atomic_tasks?.find((a) => a.id === t.id)
                    ?.dependencies ?? t.dependencies)
                : t.dependencies,
            implementation: "Atomic task compiler",
          })),
        },
      } as Plan)
    : null;
  if (!draft && tab === "history")
    return (
      <div className="history-view">
        <span className="eyebrow">PROJECT EXECUTION HISTORY</span>
        <h2>Recorded runs</h2>
        <p>Archived plans retain their immutable revisions and results.</p>
        <div className="runs-list">
          {detail.runs.map((r) => (
            <button key={r.id} disabled={busy} onClick={() => onRun(r.id)}>
              <History size={14} />
              <span>
                {r.id}
                <small>{new Date(r.started_at).toLocaleString()}</small>
              </span>
              <span>{r.status.toLowerCase().replaceAll("_", " ")}</span>
            </button>
          ))}
        </div>
        {!detail.runs.length && (
          <div className="empty-state">
            No executions recorded for this project.
          </div>
        )}
      </div>
    );
  if (!draft)
    return (
      <div className="workspace-empty">
        <GitBranch size={36} />
        <span className="eyebrow">PROJECT → PLANS → TASKS</span>
        <h2>Give your project a plan.</h2>
        <p>
          A plan describes an outcome. Its tasks define the work and the
          robot responsible for each one.
        </p>
        <button className="primary" onClick={onNew}>
          <Plus size={15} /> New plan
        </button>
        <small>
          Robot setup lives in Robots. Scene setup lives in Environment.
        </small>
      </div>
    );
  return (
    <div className="plans-workspace">
      <div className="plan-topline">
        <div>
          <span className="eyebrow">PLAN / {draft.tasks.length} TASKS</span>
          <input
            aria-label="Plan name"
            className="plan-name"
            value={draft.name}
            disabled={busy}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
          />
        </div>
        <button
          aria-label="Archive plan"
          title="Archive this plan"
          className="archive-plan"
          disabled={busy}
          onClick={onArchive}
        >
          <Trash2 size={13} />
        </button>
        <button
          className="secondary"
          disabled={busy || !dirty}
          title={dirty ? "Save this plan's changes" : "All changes saved"}
          onClick={onSave}
        >
          <Save size={13} />
          {dirty ? "Save changes" : "Saved"}
        </button>
        {running ? (
          <button
            className="stop-button"
            onClick={onStop}
            disabled={run.stop_requested}
          >
            <Square size={13} />
            {run.stop_requested ? "Stopping…" : run.mode==="physical"?"Stop physical run":"Stop simulation"}
          </button>
        ) : null}
      </div>
      <div className="plan-status" role="status">
        <span
          className={`status-dot ${revision?.valid && !stale ? "green" : ""}`}
        />
        <span>
          {stale || !revision
            ? "Not validated"
            : revision.valid
              ? "Ready for simulation"
              : "Validation needs attention"}
        </span>
        <small>
          {revision &&
            `Revision ${revision.id} · ${revision.duration.toFixed(1)}s${revision.atomic_tasks.some((t) => t.operation === "llm") ? " motion + LLM wait" : ""}`}
        </small>
        {dirty && <span className="tiny-tag">Unsaved changes</span>}
      </div>
      {run?.mode==="physical"&&<p className="inline-note">Robot joint feedback is measured. Scene objects retain configured positions unless measured object poses are available.</p>}
      <nav className="view-tabs" aria-label="Plan views" role="tablist">
        {(
          [
            { id: "tasks", name: "Tasks", icon: GitBranch },
            { id: "simulation", name: "Simulation", icon: Box },
            { id: "code", name: "Generated code", icon: Code2, expert: true },
            { id: "history", name: "Run history", icon: History },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            role="tab"
            disabled={busy}
            aria-selected={tab === t.id}
            className={`${tab === t.id ? "active" : ""} ${"expert" in t ? "expert-only" : ""}`}
            onClick={() => onTab(t.id)}
          >
            <t.icon size={14} />
            {t.name}
          </button>
        ))}
      </nav>
      <PlanningPipeline detail={detail} draft={draft} revision={revision} llm={llm} busy={busy} dirty={dirty} onChange={onChange} onDecompose={onDecompose} onBind={onBind}
        validation={validation} onValidate={onValidate} onSimulate={onSimulate} canSimulate={!!revision?.valid && !stale && !running} onSaved={onSaved} onConfigureAI={onConfigureAI} onOpenControls={onOpenControls} activity={activity}/>
      <details className="expert-only physical-run-options"><summary>Physical execution</summary><PhysicalExecution detail={detail} revision={revision} disabled={busy} onRefresh={onRefresh} onRun={onPhysicalRun}/></details>
      {tab === "tasks" ? (
        <div>
        <div className="plan-authoring">
          <div className="task-authoring">
            <div className="section-toolbar">
              <h3>
                Tasks <small>Generated from this plan · editable</small>
              </h3>
              <button
                className="text-button expert-only"
                onClick={() => setShowGoals(!showGoals)}
                disabled={busy}
              >
                <Sparkles size={13} />
                {showGoals
                  ? "Hide legacy goal editor"
                  : "Legacy goal editor"}
              </button>
            </div>
            {showGoals && (
              <section className="goal-assistant expert-only">
                <p>
                  Choose a robot for each goal. The assistant expands goals into
                  editable tasks. With an AI model, drafting uses the selected robot’s command contract; local templates remain available without one.
                </p>
                <label className="field">
                  Drafting adapter
                  <select
                    aria-label="Goal LLM adapter"
                    value={goalAdapter}
                    disabled={busy}
                    onChange={(e) => setGoalAdapter(e.target.value)}
                  >
                    <option value="">
                      Workspace default ·{" "}
                      {llm.adapters.find((p) => p.id === llm.default_id)
                        ?.name ?? "Local templates"}
                    </option>
                    {llm.adapters.map((p) => (
                      <option value={p.id} key={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                {goals.map((g, i) => (
                  <div className="goal-row" key={g.id}>
                    <select
                      aria-label={`Robot for goal ${i + 1}`}
                      value={g.robot_id}
                      disabled={busy}
                      onChange={(e) => {
                        setGoals(
                          goals.map((x) =>
                            x.id === g.id
                              ? { ...x, robot_id: e.target.value }
                              : x,
                          ),
                        );
                      }}
                    >
                      {detail.robots.map((r) => (
                        <option
                          key={r.instance.instance.id}
                          value={r.instance.instance.id}
                        >
                          {r.instance.instance.name}
                        </option>
                      ))}
                    </select>
                    <textarea
                      aria-label={`Goal ${i + 1}`}
                      value={g.prompt}
                      disabled={busy}
                      onChange={(e) => {
                        setGoals(
                          goals.map((x) =>
                            x.id === g.id
                              ? { ...x, prompt: e.target.value }
                              : x,
                          ),
                        );
                        if (goals.length === 1)
                          onChange({ ...draft, goal: e.target.value });
                      }}
                    />
                    <select
                      aria-label={`Dependency for goal ${i + 1}`}
                      value={g.dependencies[0] ?? ""}
                      disabled={busy}
                      onChange={(e) =>
                        setGoals(
                          goals.map((x) =>
                            x.id === g.id
                              ? {
                                  ...x,
                                  dependencies: e.target.value
                                    ? [e.target.value]
                                    : [],
                                }
                              : x,
                          ),
                        )
                      }
                    >
                      <option value="">Independent goal</option>
                      {goals.slice(0, i).map((x, j) => (
                        <option key={x.id} value={x.id}>
                          After goal {j + 1}
                        </option>
                      ))}
                    </select>
                    {goals.length > 1 && (
                      <button
                        aria-label={`Remove goal ${i + 1}`}
                        disabled={busy}
                        onClick={() =>
                          setGoals(
                            goals
                              .filter((x) => x.id !== g.id)
                              .map((x) => ({
                                ...x,
                                dependencies: x.dependencies.filter(
                                  (d) => d !== g.id,
                                ),
                              })),
                          )
                        }
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                ))}
                <p className="inline-note">The IDE uses the selected robot’s capabilities and scene to draft tasks, then validates them before simulation.</p>
                <div className="section-toolbar">
                  <button
                    className="text-button"
                    disabled={busy || goals.length >= 16}
                    onClick={() =>
                      setGoals([
                        ...goals,
                        {
                          id: `goal_${Date.now()}`,
                          robot_id:
                            detail.robots[
                              Math.min(goals.length, detail.robots.length - 1)
                            ].instance.instance.id,
                          prompt: "Move home.",
                          dependencies: [],
                        },
                      ])
                    }
                  >
                    <Plus size={13} />
                    Add robot goal
                  </button>
                  <button
                    className="primary generate-button"
                    disabled={busy || goals.some((g) => !g.prompt.trim())}
                    onClick={() => onDraft(goals, goalAdapter || undefined)}
                  >
                    <Sparkles size={13} />
                    {draft.tasks.length
                      ? "Replace tasks from goals"
                      : "Generate tasks"}
                    <ArrowRight size={13} />
                  </button>
                </div>
              </section>
            )}
            <div className="atomic-task-list">
              {draft.tasks.map((t, i) => (
                <button
                  className={`atomic-task ${selected === t.id ? "selected" : ""}`}
                  key={t.id}
                  onClick={() => onSelect(t.id)}
                >
                  <span className="task-index">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span>
                    <strong>{t.name}</strong>
                    <small>
                      {detail.robots.find(r=>r.instance.instance.id===t.robot_id)?.instance.instance.name??t.robot_id??"Legacy task"}{t.binding_status==="resolved"?" · commands ready":t.binding_status==="unresolved"?" · needs conversion":""}
                    </small>
                  </span>
                  <span className="task-dependencies">
                    {t.dependencies.length
                      ? `${t.dependencies.length} dependencies`
                      : "Independent"}
                  </span>
                  <span
                    className={`task-state ${run?.step_statuses[t.id] ?? ""}`}
                  >
                    {run?.step_statuses[t.id] === "done" ? (
                      <Check size={13} />
                    ) : (
                      <ArrowRight size={13} />
                    )}
                  </span>
                </button>
              ))}
            </div>
            <button
              className="add-task text-button"
              disabled={busy||!detail.robots.length}
              onClick={() => {
                const robot=detail.robots.find(r=>draft.allowed_robot_ids?.includes(r.instance.instance.id))??detail.robots[0];
                const next: TaskDefinition = {
                  id:`task_${Date.now()}`,name:"New task",intent:"",operation:"command",command:null,
                  robot_id:robot.instance.instance.id,dependencies:draft.tasks.length?[draft.tasks.at(-1)!.id]:[],
                  target:null,joint_positions:null,object_id:null,target_id:null,
                  function_calls:[],binding_status:"unresolved",authored_by:"user",repeat_count:1,
                };
                onChange({ ...draft, tasks: [...draft.tasks, next] });
                onSelect(next.id);
              }}
            >
              <Plus size={13} /> Add task
            </button>
          </div>
          <aside className="task-details">
            <section className="step-inspector">
              <span className="eyebrow">TASK INSPECTOR</span>
              {task ? (
                <>
                  <label className="field">
                    Name
                    <input
                      aria-label="Task name"
                      value={task.name}
                      disabled={busy}
                      onChange={(e) =>
                        setTask({ ...task, name: e.target.value })
                      }
                    />
                  </label>
                  <label className={`field ${task.binding_status && task.binding_status!=="legacy" ? "hidden-compatibility" : "expert-only"}`}>
                    Legacy task type
                    <select
                      aria-label="Task type"
                      value={task.operation}
                      disabled={busy}
                      onChange={(e) =>
                        setTask({
                          ...task,
                          operation: e.target
                            .value as TaskDefinition["operation"],
                          command: e.target.value === "command" ? (()=>{const model=detail.robots.find(r=>r.instance.instance.id===task.robot_id)?.model??detail.model;const target=Object.keys(model.actuators.actuators)[0];const actuator=model.actuators.actuators[target];return {type:"SET_ACTUATOR" as const,target,unit:actuator.unit as "rad"|"m",value:Math.max(actuator.min,Math.min(0,actuator.max))};})():null,
                          target: null,
                          joint_positions: null,
                          object_id: null,
                          target_id: null,
                          robot_id:
                            e.target.value === "llm"
                              ? ""
                              : task.robot_id ||
                                detail.robots[0].instance.instance.id,
                          llm_input: task.llm_input || "",
                        })
                      }
                    >
                      {["move", "grasp", "release", "verify", "command", "llm"].map(
                        (o) => (
                          <option key={o} value={o}>
                            {o === "command" ? "Robot command task" : o === "llm"
                              ? "LLM task"
                              : o[0].toUpperCase() + o.slice(1)}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  {task.operation !== "llm" && (
                    <label className="field">
                      Assigned robot
                      <select
                        aria-label="Task robot"
                        value={task.robot_id}
                        disabled={busy}
                        onChange={(e) =>
                          setTask({ ...task, robot_id: e.target.value, ...(task.binding_status&&task.binding_status!=="legacy"?{function_calls:[],binding_status:"unresolved" as const,binding_error:null,binding_fingerprint:null}: {}) })
                        }
                      >
                        {detail.robots.map((r) => (
                          <option
                            key={r.instance.instance.id}
                            value={r.instance.instance.id}
                          >
                            {r.instance.instance.name} ·{" "}
                            {r.instance.instance.id}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {task.binding_status&&task.binding_status!=="legacy"&&<TaskCommandEditor detail={detail} draft={draft} task={task} busy={busy} onChange={onChange}/>}
                  <label className={task.operation === "llm" ? "field" : "field expert-only"}>
                    {task.operation === "llm" ? "AI model" : "Task LLM (override for this task)"}
                    <select
                      aria-label="Task LLM adapter"
                      value={task.llm_adapter_id ?? ""}
                      disabled={busy}
                      onChange={(e) =>
                        setTask({
                          ...task,
                          llm_adapter_id: e.target.value || null,
                        })
                      }
                    >
                      <option value="">
                        Workspace default ·{" "}
                        {llm.adapters.find((p) => p.id === llm.default_id)
                          ?.name ?? "None configured"}
                      </option>
                      {task.llm_adapter_id &&
                        !llm.adapters.some(
                          (p) => p.id === task.llm_adapter_id,
                        ) && (
                          <option value={task.llm_adapter_id}>
                            Missing adapter · select another
                          </option>
                        )}
                      {llm.adapters.map((p) => (
                        <option value={p.id} key={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {task.binding_status && task.binding_status!=="legacy" ? null : task.operation === "llm" ? (
                    <>
                      <label className="field">
                        Input
                        <textarea
                          aria-label="Task LLM input"
                          value={task.llm_input ?? ""}
                          disabled={busy}
                          onChange={(e) =>
                            setTask({ ...task, llm_input: e.target.value })
                          }
                        />
                      </label>
                      <p className="inline-note">
                        Returns an answer during execution. Robot trajectories
                        pause while waiting. Reference an earlier LLM dependency
                        with {"{{tasks.task_id.answer}}"}. Answers never become
                        actuator commands.
                      </p>
                    </>
                  ) : task.operation === "command" && task.command ? (
                    <>
                      <StandardTaskEditor model={detail.robots.find(r=>r.instance.instance.id===task.robot_id)?.model??detail.model} command={task.command} disabled={busy} onChange={command=>setTask({...task,command})}/>
                      <details className="inline-note"><summary>Shared scene resources</summary>
                        <p>Reserve objects/destinations used by this task so conflicting tasks serialize. A resource association does not establish contact or move the object.</p>
                        {(["object_id","target_id"] as const).map(field=><label className="field" key={field}>{field==="object_id"?"Object resource":"Destination resource"}<select aria-label={`Command ${field==="object_id"?"object":"destination"} resource`} value={task[field]??""} disabled={busy} onChange={e=>setTask({...task,[field]:e.target.value||null})}><option value="">None</option>{detail.objects.filter(o=>o.kind===(field==="object_id"?"object":task.placement==="on_surface"?"obstacle":"region")).map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></label>)}
                      </details>
                    </>
                  ) : task.operation === "move" ? (
                    <>
                      <label className="field">
                        Motion target
                        <select
                          aria-label="Motion target type"
                          value={
                            task.target
                              ? "cartesian"
                              : task.joint_positions
                                ? "joints"
                                : "home"
                          }
                          disabled={busy}
                          onChange={(e) =>
                            setTask({
                              ...task,
                              target:
                                e.target.value === "cartesian"
                                  ? { x: 0.34, y: -0.16, z: 0.25 }
                                  : null,
                              joint_positions:
                                e.target.value === "joints"
                                  ? {
                                      ...detail.robots.find(
                                        (r) =>
                                          r.instance.instance.id ===
                                          task.robot_id,
                                      )!.instance.initial_configuration
                                        .actuator_positions,
                                    }
                                  : null,
                            })
                          }
                        >
                          <option value="home">
                            Saved initial configuration
                          </option>
                          <option value="cartesian">World coordinates</option>
                          <option value="joints">Joint positions</option>
                        </select>
                      </label>
                      {task.target && (
                        <div className="coordinate-inputs">
                          {(["x", "y", "z"] as const).map((a) => (
                            <label key={a}>
                              {a.toUpperCase()} · m
                              <input
                                aria-label={`Task target ${a}`}
                                type="number"
                                step=".01"
                                value={task.target![a]}
                                disabled={busy}
                                onChange={(e) =>
                                  setTask({
                                    ...task,
                                    target: {
                                      ...task.target!,
                                      [a]: Number(e.target.value),
                                    },
                                  })
                                }
                              />
                            </label>
                          ))}
                        </div>
                      )}
                      {task.joint_positions &&
                        Object.entries(task.joint_positions).map(
                          ([key, value]) => (
                            <label className="field" key={key}>
                              {key}
                              <input
                                aria-label={`Task joint ${key}`}
                                type="number"
                                step=".01"
                                value={value}
                                disabled={busy}
                                onChange={(e) =>
                                  setTask({
                                    ...task,
                                    joint_positions: {
                                      ...task.joint_positions,
                                      [key]: Number(e.target.value),
                                    },
                                  })
                                }
                              />
                            </label>
                          ),
                        )}
                      <label className="field">
                        Resource object · optional
                        <select
                          aria-label="Move resource object"
                          value={task.object_id ?? ""}
                          disabled={busy}
                          onChange={(e) =>
                            setTask({
                              ...task,
                              object_id: e.target.value || null,
                            })
                          }
                        >
                          <option value="">No object resource</option>
                          {detail.objects
                            .filter((o) => o.kind === "object")
                            .map((o) => (
                              <option key={o.id} value={o.id}>
                                {o.name}
                              </option>
                            ))}
                        </select>
                      </label>
                      <label className="field">Placement<select aria-label="Task placement" value={task.placement??"inside"} disabled={busy} onChange={e=>setTask({...task,placement:e.target.value as "inside"|"on_surface",target_id:null})}><option value="inside">Inside destination area</option><option value="on_surface">On support surface</option></select></label>
                      <label className="field">
                        Destination resource · optional
                        <select
                          aria-label="Move destination resource"
                          value={task.target_id ?? ""}
                          disabled={busy}
                          onChange={(e) =>
                            setTask({
                              ...task,
                              target_id: e.target.value || null,
                            })
                          }
                        >
                          <option value="">No destination resource</option>
                          {detail.objects
                            .filter((o) => o.kind === ((task.placement??"inside")==="on_surface"?"obstacle":"region"))
                            .map((o) => (
                              <option key={o.id} value={o.id}>
                                {o.name}
                              </option>
                            ))}
                        </select>
                      </label>
                    </>
                  ) : (
                    <>
                      <label className="field">
                        Object
                        <select
                          aria-label="Task object"
                          value={task.object_id ?? ""}
                          disabled={busy}
                          onChange={(e) =>
                            setTask({
                              ...task,
                              object_id: e.target.value || null,
                              target_id: e.target.value ? task.target_id : null,
                            })
                          }
                        >
                          <option value="">
                            {task.operation === "verify"
                              ? "Verify joint state"
                              : "Choose object"}
                          </option>
                          {detail.objects
                            .filter((o) => o.kind === "object")
                            .map((o) => (
                              <option value={o.id} key={o.id}>
                                {o.name}
                              </option>
                            ))}
                        </select>
                      </label>
                      {task.operation === "verify" && task.object_id && (
                        <label className="field">
                          Destination
                          <select
                            aria-label="Task destination"
                            disabled={busy}
                            value={task.target_id ?? ""}
                            onChange={(e) =>
                              setTask({
                                ...task,
                                target_id: e.target.value || null,
                              })
                            }
                          >
                            <option value="">Choose destination</option>
                            {detail.objects
                              .filter((o) => o.kind === ((task.placement??"inside")==="on_surface"?"obstacle":"region"))
                              .map((o) => (
                                <option value={o.id} key={o.id}>
                                  {o.name}
                                </option>
                              ))}
                          </select>
                        </label>
                      )}
                    </>
                  )}
                  <div className="task-refinement expert-only">
                    <label className="field">
                      Draft a refinement
                      <textarea
                        aria-label="Task refinement instruction"
                        placeholder="Describe how to improve this task…"
                        value={refinement}
                        disabled={busy}
                        onChange={(e) => setRefinement(e.target.value)}
                      />
                    </label>
                    <button
                      className="secondary"
                      disabled={
                        busy ||
                        !refinement.trim() ||
                        !(task.llm_adapter_id || llm.default_id)
                      }
                      onClick={() => onRefine(task.id, refinement)}
                    >
                      <Sparkles size={13} /> Draft task refinement
                    </button>
                    <small>
                      Uses this task’s AI model. Review the proposal before
                      saving.
                    </small>
                  </div>
                  <fieldset className="dependency-field">
                    <legend>Wait for tasks</legend>
                    {draft.tasks
                      .filter((t) => t.id !== task.id)
                      .map((t) => (
                        <label key={t.id}>
                          <input
                            type="checkbox"
                            checked={task.dependencies.includes(t.id)}
                            disabled={busy}
                            onChange={(e) =>
                              setTask({
                                ...task,
                                dependencies: e.target.checked
                                  ? [...task.dependencies, t.id]
                                  : task.dependencies.filter((d) => d !== t.id),
                              })
                            }
                          />
                          {t.name} <small>{t.robot_id}</small>
                        </label>
                      ))}
                    {draft.tasks.length === 1 && (
                      <small>No other tasks yet.</small>
                    )}
                  </fieldset>
                  <small>
                    Shared robots, objects and destination regions are also
                    serialized during compilation.
                  </small>
                  <button
                    className="text-button danger"
                    title={draft.tasks.some(t=>t.dependencies.includes(task.id)) ? "Remove or replace dependent tasks' prerequisite first" : "Delete this task"}
                    disabled={busy || draft.tasks.some(t=>t.dependencies.includes(task.id))}
                    onClick={() =>
                      onChange({
                        ...draft,
                        tasks: draft.tasks.filter((t) => t.id !== task.id),
                      })
                    }
                  >
                    <Trash2 size={13} /> Delete task
                  </button>
                </>
              ) : (
                <p>
                  Select a task to edit its robot, instruction, commands and
                  dependencies.
                </p>
              )}
            </section>
            <section className="graph-panel">
              <div className="panel-heading">
                <span>DEPENDENCY GRAPH</span>
                <GitBranch size={13} />
              </div>
              <div className="graph-content">
                <TaskGraph
                  plan={graph}
                  run={run}
                  selected={selected}
                  onSelect={onSelect}
                />
              </div>
            </section>
            {!!revision && (
              <section className="validation-list">
                <span className="eyebrow">
                  COMPILED VALIDATION {stale ? "· OUTDATED" : ""}
                </span>
                {revision.checks.map((c) => (
                  <details key={c.id} className={c.status}>
                    <summary>
                      {c.status === "passed"
                        ? "✓"
                        : c.status === "failed"
                          ? "×"
                          : "·"}{" "}
                      {c.label}
                    </summary>
                    <p>{c.message}</p>
                  </details>
                ))}
              </section>
            )}
          </aside>
        </div>
        </div>
      ) : tab === "simulation" ? (
        <div className="simulation-workspace">
          {reachability.controls}
          <div className="plan-scene scene-content">
            <Scene
              validationMarkers={revision?.validation_report?.findings}
              workspaces={reachability.overlay}
              workspaceFocus={reachability.focus}
              projectId={detail.project.id}
              model={primary.model}
              q={primary.state.positions}
              robots={detail.robots}
              objects={detail.objects}
              frame={frame}
              path={revision?.frames ?? []}
              showGrid
              resetKey={0}
            />
            <span className="viewport-badge">
              {preview !== null
                ? "PREDICTED PREVIEW"
                : run?.finished_at
                  ? "RECORDED RESULT"
                  : running
                    ? "EXECUTION FEEDBACK"
                    : "ENVIRONMENT STATE"}{" "}
              · {detail.adapter === "mock" ? "BUILT-IN" : "ISAAC SIM"}
            </span>
          </div>
          {revision && (
            <div className="timeline">
              <button onClick={() => setPreview(null)} disabled={running}>
                Feedback
              </button>
              <input
                aria-label="Preview timeline"
                type="range"
                min={0}
                max={revision.duration}
                step=".033"
                disabled={running}
                value={preview ?? run?.elapsed ?? 0}
                onChange={(e) => setPreview(Number(e.target.value))}
              />
              <small>
                {(preview ?? run?.elapsed ?? 0).toFixed(1)} /{" "}
                {revision.duration.toFixed(1)}s
              </small>
            </div>
          )}
          <section className="execution-panel">
            <div className="section-toolbar">
              <h3>Execution & verification</h3>
              {run && (
                <>
                  <span
                    className={`run-status ${run.status === "SIMULATION_PASSED" ? "success" : ""}`}
                  >
                    {run.status.toLowerCase().replaceAll("_", " ")}
                  </span>
                  <button
                    aria-label="Export run result"
                    onClick={() =>
                      download(
                        `run-${run.id}.json`,
                        JSON.stringify(run, null, 2),
                      )
                    }
                  >
                    <Download size={13} />
                  </button>
                </>
              )}
            </div>
            {run ? (
              <>
                <progress value={run.progress} max={1} />
                <div className="run-summary">
                  <span>
                    Stop requested: {run.stop_requested ? "yes" : "no"}
                  </span>
                  <span>
                    Stopped:{" "}
                    {run.stopped_verified ? "confirmed" : "unconfirmed"}
                  </span>
                  <span>
                    Postconditions:{" "}
                    {run.evidence.postcondition_passed
                      ? "passed"
                      : "not verified"}
                  </span>
                </div>
                {!!run.evidence.llm && (
                  <section className="llm-results">
                    <h3>LLM answers</h3>
                    {Object.entries(
                      run.evidence.llm as Record<
                        string,
                        { answer: string; model: string }
                      >,
                    ).map(([id, result]) => (
                      <article key={id}>
                        <strong>
                          {draft.tasks.find((t) => t.id === id)?.name ?? id}
                        </strong>
                        <small>{result.model}</small>
                        <pre className="llm-answer">{result.answer}</pre>
                      </article>
                    ))}
                  </section>
                )}
                <div className="execution-logs">
                  {run.logs.map((l, i) => (
                    <div key={i} className={`log-line ${l.level}`}>
                      <time>{new Date(l.timestamp).toLocaleTimeString()}</time>
                      {l.message}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p>
                Compile the plan, inspect its validation, then select Simulate.
                Physical plan execution is unavailable.
              </p>
            )}
          </section>
        </div>
      ) : tab === "code" ? (
        <Suspense fallback={<div className="empty-state">Loading editor…</div>}>
          <CodeView plan={revision} />
        </Suspense>
      ) : (
        <div className="history-view">
          <span className="eyebrow">IMMUTABLE EXECUTION HISTORY</span>
          <h2>Runs for this plan</h2>
          <p>
            Each run reopens its exact compiled revision. Editing this plan does
            not rewrite past results.
          </p>
          <label className="history-filter">
            <input
              type="checkbox"
              checked={allRuns}
              onChange={(e) => setAllRuns(e.target.checked)}
            />{" "}
            Show all project runs
          </label>
          <div className="runs-list">
            {detail.runs
              .filter((r) => allRuns || r.definition_id === draft.id)
              .map((r) => (
                <button key={r.id} onClick={() => onRun(r.id)} disabled={busy}>
                  <History size={14} />
                  <span>
                    {r.id}
                    <small>{new Date(r.started_at).toLocaleString()}</small>
                  </span>
                  <span>{r.status.toLowerCase().replaceAll("_", " ")}</span>
                </button>
              ))}
          </div>
          {!detail.runs.length && (
            <div className="empty-state">
              No executions recorded for this project.
            </div>
          )}
          {run && (
            <pre className="evidence">
              {JSON.stringify(run.evidence, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

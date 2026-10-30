import InstallApp from "./InstallApp";
import Feedback from "../../SERVER_CLIENT/client/src/ui/Feedback";
import {randomId} from "../../SERVER_CLIENT/client/src/id";
import NvidiaLogo from "../../SERVER_CLIENT/client/src/branding/NvidiaLogo";
import { useEffect, useRef, useState, Suspense, lazy } from "react";
import {
  ArrowRight,
  Box,
  Check,
  ChevronRight,
  Clock,
  Mic,
  RefreshCw,
  ScanLine,
  Search,
  Send,
  Square,
  X,
  RotateCcw,
  Move,
  Hand,
} from "lucide-react";
import { api, post, route } from "./api";
import type { AIModelChoice, Asset, Command, Progress, Project, Workspace } from "./types";
import FloorPlan from "./FloorPlan";
import Rooms from "./Rooms";
import GpuStart from "./GpuStart";
import RobotLogo from "../../SERVER_CLIENT/client/src/branding/RobotLogo";
import {useCloudActivity} from "../../SERVER_CLIENT/client/src/ui/useCloudActivity";
import { useVoice } from "./useVoice";
const Scene = lazy(() => import("../../SERVER_CLIENT/client/src/Scene"));
export default function App() {
  const [projects, setProjects] = useState<Project[]>([]),
    [projectId, setProjectId] = useState(
      localStorage.getItem("business.project") ?? "",
    );
  const [workspace, setWorkspace] = useState<Workspace | null>(null),
    [section, setSection] = useState<"workspace" | "rooms">("workspace");
  useCloudActivity(!!workspace?.cloud_session,true);
  const [input, setInput] = useState(""),
    [search, setSearch] = useState(""),
    [selected, setSelected] = useState(""),
    [view, setView] = useState<"3d" | "map">("3d");
  const [clarifications,setClarifications]=useState<Record<string,string>>({});
  // Planner LLM and Task LLM for the next command; empty values use the workspace settings.
  const [ai, setAI] = useState<AIModelChoice | null>(null),
    [planner, setPlanner] = useState(""),
    [taskModel, setTaskModel] = useState("");
  useEffect(() => { void api<AIModelChoice>("/ai-models").then(setAI).catch(() => setAI(null)); }, []);
  const [command, setCommand] = useState<Command | null>(null),
    [run, setRun] = useState<Progress | null>(null);
  const [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [reset, setReset] = useState(0),
    [focus, setFocus] = useState<{ id: string; request: string }>();
  const currentProject = useRef(projectId);
  currentProject.current = projectId;
  function updateInput(value: string) {
    setInput(value);
    if (command && !command.run_id) setCommand(null);
  }
  const voice = useVoice(input, updateInput, setError);
  const active = !!command?.run_id && (!run || !run.finished_at);
  async function refresh() {
    const id = currentProject.current;
    if (!id) return;
    const next = await api<Workspace>(route(id) + "/workspace");
    if (currentProject.current === id) setWorkspace(next);
  }
  useEffect(() => {
    api<Project[]>("/projects")
      .then((list) => {
        setProjects(list);
        setProjectId((current) =>
          list.some((p) => p.id === current) ? current : (list[0]?.id ?? ""),
        );
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    let alive = true;
    setWorkspace(null);
    setCommand(null);
    setRun(null);
    setSelected("");
    setError("");
    setNotice("");
    setSection("workspace");
    voice.stop();
    if (!projectId) return;
    localStorage.setItem("business.project", projectId);
    api<Workspace>(route(projectId) + "/workspace")
      .then((w) => {
        if (!alive) return;
        setWorkspace(w);
        const previous = w.commands.find((c) => c.run_id);
        if (previous) setCommand(previous);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [projectId]);
  useEffect(()=>{
    if(!command?.physical_status||command.run_id||!projectId)return;
    const timer=setInterval(()=>void api<Command>(route(projectId)+"/commands/"+command.id).then(setCommand).catch(e=>setError(e.message)),1000);
    return()=>clearInterval(timer)
  },[projectId,command?.id,command?.run_id,command?.physical_status]);
  useEffect(() => {
    if (!command?.run_id || !projectId) return;
    let alive = true;
    const read = () =>
      api<Progress>(route(projectId) + "/commands/" + command.id + "/run")
        .then((r) => {
          if (alive) setRun(r);
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    void read();
    const timer = setInterval(() => void read(), 900);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [projectId, command?.id, command?.run_id]);
  useEffect(() => {
    if (!projectId) return;
    const timer = setInterval(
      () => {
        if (document.visibilityState === "visible")
          void refresh().catch((e) => setError(e.message));
      },
      active ? 1500 : 6000,
    );
    return () => clearInterval(timer);
  }, [projectId, active]);
  async function work(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  function selectAsset(a: Asset) {
    setSelected(a.id);
    if (a.category !== "robot")
      setFocus({ id: a.planning_id ?? a.id, request: randomId() });
  }
  const assets = workspace?.assets.filter((a) => a.category !== "robot") ?? [];
  const chosen = assets.find((a) => a.id === selected);
  const movable = assets.filter((a) => a.kind === "object" && a.planning_id),
    destinations = assets.filter(
      (a) => ["region", "obstacle"].includes(a.kind) && a.planning_id,
    );
  const [itemId, setItemId] = useState(""),
    [fromId, setFromId] = useState(""),
    [toId, setToId] = useState("");
  useEffect(() => {
    setItemId("");
    setFromId("");
    setToId("");
  }, [projectId]);
  function guided() {
    const item = movable.find((a) => a.id === itemId) ?? movable[0],
      to = destinations.find((a) => a.id === toId),
      from = destinations.find((a) => a.id === fromId);
    if (!item || !to) return;
    updateInput(
      `Move ${item.name}${from ? " from " + from.name : ""} to ${to.name}`,
    );
    setNotice("Your command is ready to review.");
  }
  const shownObjects =
    workspace?.objects.map((o) => ({
      ...o,
      name: assets.find((a) => a.planning_id === o.id)?.name ?? o.name,
      position: run?.frame?.objects[o.id] ?? o.position,
    })) ?? [];
  const robots =
    workspace?.robots.map((r) => ({
      ...r,
      model: { ...r.model, adapters: {} },
      state: {
        ...r.state,
        ...(run?.robot_states?.[r.instance.instance.id] ?? {}),
      },
    })) ?? [];
  const status =
    run?.stop_requested && !run.stopped_verified
      ? "Stopping…"
      : ["COMPLETED", "SIMULATION_PASSED"].includes(run?.status ?? "")
        ? "Completed"
        : run?.status === "CANCELLED"
          ? "Stopped"
          : run?.status === "FAILED"
            ? "Needs attention"
            : active
              ? "Working"
              : command?.status === "needs_clarification" ? "A little more detail needed"
              : command?.status === "unsupported" ? "This request is not supported"
              : command?.status === "unresolved" || command?.status === "validation_failed" ? "Operator review needed"
              : command && !command.run_id
                ? "Ready for review"
                : "Ready";
  return (
    <div className="business-shell">
      <header className="app-header">
        <a
          className="brand"
          href="/business/"
          aria-label="RoboDE Workspace home"
        >
          <span className="brand-mark">
            <RobotLogo />
          </span>
          <span>
            RoboDE <strong>Workspace</strong>
            <small>Make your workspace work for you.</small>
          </span>
        </a>
        <div className="header-actions">
          <InstallApp />
          <button
            className={section === "rooms" ? "active" : ""}
            onClick={() => {
              voice.stop();
              setSection(section === "rooms" ? "workspace" : "rooms");
            }}
          >
            <ScanLine size={18} />
            <span>Room capture</span>
          </button>
          <span className="simulation-tag">
            <span /> Simulation workspace
          </span>
        </div>
      </header>
      <div className="workspace-selector">
        <label>
          YOUR WORKSPACE
          <select
            aria-label="Choose workspace"
            value={projectId}
            disabled={!!busy || active}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {projects.map((p) => (
              <option value={p.id} key={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <span className="workspace-location">
          {workspace?.backend === "isaac_sim" ? (
            <span className="nvidia-tool-heading">
              <NvidiaLogo />
              Isaac Sim
            </span>
          ) : (
            "Built-in simulator"
          )}
        </span>
        <button
          className="icon-button"
          aria-label="Refresh workspace"
          onClick={() => void work("Refreshing workspace", refresh)}
          disabled={!!busy}
        >
          <RefreshCw size={18} />
        </button>
      </div>
      <Feedback message={error} onDismiss={() => setError("")} />
      {workspace?.cloud_session && <div className="cloud-session-note" role="note">Cloud session · stops after 10 minutes without activity · maximum 2 hours per start.</div>}
      {!workspace ? (
        <div className="loading-page" role="status">
          <div className="spinner" />
          <h2>
            {projects.length
              ? "Opening your workspace…"
              : "Getting your workspaces ready…"}
          </h2>
          {!projects.length && (
            <p>Projects configured in RoboDE appear here.</p>
          )}
        </div>
      ) : section === "rooms" ? (
        <Rooms
          key={projectId}
          workspace={workspace}
          onBack={() => setSection("workspace")}
          onRefresh={() => void refresh()}
        />
      ) : (
        <main className="workspace-page">
          <div className="page-heading">
            <div>
              <span className="overline">WORKSPACE OVERVIEW</span>
              <h1>A clear view. A simple command.</h1>
              <p>
                See what’s available, tell your robot what you need, and review
                before it moves.
              </p>
            </div>
            <span
              className={`availability ${workspace.connected ? "online" : "offline"}`}
            >
              <span />
              {workspace.connected
                ? "Workspace connected"
                : workspace.source === "configured_preview"
                  ? "Saved configuration"
                  : "Last observed state"}
            </span>
          </div>
          {!workspace.connected && (
            <div className="callout">
              This workspace is offline. The view shows saved configuration or
              last observed state. Connect the simulator to review and run
              commands.
            </div>
          )}
          {!workspace.connected && workspace.backend === "isaac_sim" && (
            <GpuStart
              onReady={async () => {
                await post(route(projectId) + "/connect");
                await refresh();
              }}
            />
          )}
          <div className="operations-layout">
            <section className="workspace-visual panel">
              <div className="visual-toolbar">
                <div>
                  <span className="overline">{workspace.project.name}</span>
                  <h2>Your working environment</h2>
                </div>
                <div
                  className="view-switch"
                  role="group"
                  aria-label="Workspace view"
                >
                  <button
                    aria-pressed={view === "3d"}
                    onClick={() => setView("3d")}
                  >
                    3D view
                  </button>
                  <button
                    aria-pressed={view === "map"}
                    onClick={() => setView("map")}
                  >
                    Floor plan
                  </button>
                </div>
              </div>
              <div className="world-view">
                {view === "map" ? (
                  <FloorPlan
                    assets={workspace.assets.map(asset => ({
                      ...asset,
                      position: (asset.planning_id && run?.frame?.objects[asset.planning_id]) || asset.position,
                    }))}
                    selected={selected}
                    onSelect={selectAsset}
                  />
                ) : (
                  <Suspense
                    fallback={
                      <div className="friendly-empty">
                        Opening 3D workspace…
                      </div>
                    }
                  >
                    <Scene
                      model={robots[0].model}
                      q={robots[0].state.positions}
                      robots={robots}
                      objects={shownObjects}
                      path={[]}
                      showGrid
                      resetKey={reset}
                      projectId={projectId}
                      focus={focus}
                      objectLabels
                      appearance="business"
                      visualBounds={assets
                        .filter((a) => !a.planning_id && a.category !== "robot")
                        .map((a) => ({
                          ...a,
                          kind: "obstacle" as const,
                          mass_kg: 0,
                        }))}
                      onSelectObject={(id) => {
                        const a = assets.find(
                          (a) => a.id === id || a.planning_id === id,
                        );
                        if (a) selectAsset(a);
                      }}
                    />
                  </Suspense>
                )}
                <span className="scene-legend">
                  {workspace.source === "isaac_sim"
                    ? "Live Isaac Sim positions"
                    : "Project simulation"}{" "}
                  · simplified geometry
                </span>
                {view === "3d" && (
                  <div className="visual-controls">
                    <button
                      aria-label="Reset workspace view"
                      onClick={() => {
                        setFocus(undefined);
                        setReset(reset + 1);
                      }}
                    >
                      <RotateCcw size={16} /> Reset view
                    </button>
                    <span>
                      <Hand size={15} /> Drag to look · pinch to zoom
                    </span>
                  </div>
                )}
              </div>
              <div className="workspace-summary">
                <span>
                  <Box size={17} />
                  {assets.length} named assets
                </span>
                <span>
                  <Move size={17} />
                  {robots.length} {robots.length === 1 ? "robot" : "robots"}{" "}
                  available
                </span>
                <span className="data-source">{workspace.inventory_scope}</span>
              </div>
              {chosen && (
                <div className="selected-asset">
                  <div>
                    <strong>{chosen.name}</strong>
                    <small>
                      {chosen.read_only
                        ? "Visual asset · available to view"
                        : chosen.kind === "object"
                          ? "Movable item"
                          : chosen.kind === "region"
                            ? "Destination area"
                            : "Support surface / fixed obstacle"}
                    </small>
                  </div>
                  {chosen.kind === "object" && chosen.planning_id && (
                    <button
                      onClick={() => {
                        setItemId(chosen.id);
                        setNotice(
                          chosen.name +
                            " selected. Choose a destination below.",
                        );
                      }}
                    >
                      Use in a command <ChevronRight size={17} />
                    </button>
                  )}
                  <button
                    aria-label="Close asset details"
                    onClick={() => setSelected("")}
                  >
                    <X size={17} />
                  </button>
                </div>
              )}
            </section>
            <aside className="command-panel panel">
              <div className="command-heading">
                <span className="soft-icon">
                  <Send size={22} />
                </span>
                <h2>What would you like done?</h2>
              </div>
              <p className="muted">
                Use the asset names you see in your workspace.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  voice.stop();
                  void work("Preparing your command…", async () => {
                    setRun(null);
                    setCommand(null);
                    const result = await post<Command>(
                      route(projectId) + "/commands",
                      { instruction: input, request_id: randomId(), planner_adapter_id: planner || null, task_adapter_id: taskModel || null },
                    );
                    setCommand(result);
                    setNotice("Review the proposed tasks before starting.");
                  });
                }}
              >
                <label className="sr-only" htmlFor="business-command">
                  Your command
                </label>
                <textarea
                  id="business-command"
                  aria-label="Your command"
                  placeholder="Move Apple from Table1 to Table2"
                  value={input}
                  maxLength={4000}
                  onChange={(e) => updateInput(e.target.value)}
                  disabled={!!busy || active}
                />
                <div className="composer-actions">
                  <button
                    className={
                      voice.listening ? "mic-button listening" : "mic-button"
                    }
                    aria-label={
                      voice.listening ? "Stop listening" : "Speak a command"
                    }
                    type="button"
                    aria-pressed={voice.listening}
                    onClick={voice.toggle}
                    disabled={!!busy || active}
                  >
                    <Mic size={20} />
                    {voice.listening ? "Listening…" : "Speak"}
                  </button>
                  <button
                    className="primary"
                    type="submit"
                    disabled={
                      !!busy ||
                      active ||
                      !input.trim() ||
                      !workspace.connected ||
                      !!workspace.active_run
                    }
                  >
                    <span>{busy || "Review command"}</span>
                    {busy ? (
                      <span className="spinner small" />
                    ) : (
                      <ArrowRight size={18} />
                    )}
                  </button>
                </div>
                <p className="voice-note">
                  {voice.supported
                    ? "Your browser may send audio to its speech provider. Voice only fills the text; you review it before sending."
                    : "Voice is unavailable in this browser. Type, or use your device keyboard’s microphone."}
                </p>
              </form>
              {ai && ai.models.length > 0 && (
                <details className="ai-choice">
                  <summary>AI models for this command</summary>
                  {([["Planner LLM", planner, setPlanner, ai.planner_adapter_id], ["Task LLM", taskModel, setTaskModel, ai.task_adapter_id]] as const).map(([label, value, set, fallback]) => (
                    <label key={label}>
                      {label}
                      <select aria-label={label} value={value} disabled={!!busy || active} onChange={(e) => set(e.target.value)}>
                        <option value="">Workspace setting · {ai.models.find((m) => m.id === fallback)?.model ?? "none"}</option>
                        {ai.models.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.model}</option>)}
                      </select>
                    </label>
                  ))}
                  <p className="muted">The Planner LLM splits your command into tasks. The Task LLM turns each task into robot actions.</p>
                </details>
              )}
              <details className="guided-command">
                <summary>Prefer to choose from a list?</summary>
                <div className="guided-fields">
                  <label>
                    Move
                    <select
                      aria-label="Choose item"
                      value={itemId || movable[0]?.id || ""}
                      onChange={(e) => setItemId(e.target.value)}
                    >
                      {movable.map((a) => (
                        <option value={a.id} key={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    From <small>optional</small>
                    <select
                      aria-label="Choose source"
                      value={fromId}
                      onChange={(e) => setFromId(e.target.value)}
                    >
                      <option value="">Current location</option>
                      {destinations.map((a) => (
                        <option value={a.id} key={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    To
                    <select
                      aria-label="Choose destination"
                      value={toId}
                      onChange={(e) => setToId(e.target.value)}
                    >
                      <option value="">Choose a destination</option>
                      {destinations.map((a) => (
                        <option value={a.id} key={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="secondary"
                    disabled={!toId || !movable.length || active || !!busy}
                    onClick={guided}
                  >
                    Write this command <ArrowRight size={16} />
                  </button>
                </div>
              </details>
              {notice && (
                <p className="success-message" role="status">
                  <Check size={16} />
                  {notice}
                </p>
              )}
              {workspace.active_run&&<button className="stop-command full-width" disabled={!!busy} onClick={()=>void work("Requesting Stop…",async()=>{await post(route(projectId)+"/stop");setNotice("Stop requested. Waiting for confirmed stopped feedback.")})}>Stop workspace execution</button>}
              {!command && (
                <div className="how-it-works">
                  <h3>A little direction goes a long way.</h3>
                  <ol>
                    <li>
                      <span>1</span>Tell us what to move and where.
                    </li>
                    <li>
                      <span>2</span>Review the proposed tasks.
                    </li>
                    <li>
                      <span>3</span>Start the simulation and watch it happen.
                    </li>
                  </ol>
                </div>
              )}
              {command && (
                <div className="command-review" aria-label="Command review">
                  <div className="review-heading">
                    <h3>{status}</h3>
                    <span>
                      <Clock size={14} />
                      {Math.ceil(command.duration)} sec estimated
                    </span>
                  </div>
                  <p className="command-text">“{command.instruction}”</p>
                  <p className="muted">Assigned to {command.robot_name}</p>
                  {command.ai_models&&<p className="muted">Planned by {command.ai_models.planner ?? "no model"} · tasks converted by {command.ai_models.task ?? "no model"}</p>}
                  {command.planning_error&&<p className="error-note" role="alert">{command.planning_error}</p>}
                  {command.clarification_questions?.map(question=><label className="field" key={question}>{question}<input aria-label={question} value={clarifications[question]??""} onChange={e=>setClarifications({...clarifications,[question]:e.target.value})}/></label>)}
                  {command.status==="needs_clarification"&&<button className="primary full-width" disabled={!!busy||command.clarification_questions?.some(q=>!clarifications[q]?.trim())} onClick={()=>void work("Updating the plan…",async()=>setCommand(await post(route(projectId)+"/commands/"+command.id+"/clarify",{answers:clarifications})))}>Continue with these details</button>}
                  {command.validation_report&&<p className={command.validation_report.status==="passed"?"muted":"error-note"} role="status">Motion check: {command.validation_report.status}. {command.validation_report.status==="incomplete"?"Preview is available; a physical run needs the IDE operator to complete the checks.":""}</p>}
                  {command.checks.filter(c=>c.status!=="passed").map((c,i)=><p className="error-note" key={i}>{c.message}</p>)}
                  <ol className="task-checklist">
                    {command.steps.map((s, i) => (
                      <li
                        key={s.id}
                        className={
                          run?.task_statuses[s.id] === "completed"
                            ? "done"
                            : run?.current_step === s.id
                              ? "in-progress"
                              : ""
                        }
                      >
                        <span>
                          {run?.task_statuses[s.id] === "completed" ? (
                            <Check size={14} />
                          ) : (
                            i + 1
                          )}
                        </span>
                        {s.name}
                      </li>
                    ))}
                  </ol>
                  {run && (
                    <>
                      <progress
                        value={run.progress}
                        max={1}
                        aria-label="Simulation progress"
                      />
                      <p className="run-status" role="status">
                        {status}
                        {run.stop_requested
                          ? run.stopped_verified
                            ? " · stopped feedback confirmed"
                            : " · waiting for stopped feedback"
                          : ""}
                      </p>
                      {run.status === "FAILED" && (
                        <p className="error-note">
                          {run.logs.filter((l) => l.level === "error").at(-1)
                            ?.message ??
                            "The simulation did not complete. Ask your workspace operator to review it."}
                        </p>
                      )}
                    </>
                  )}
                  {command.validation_report?.status==="passed"&&!command.run_id&&<button className="secondary full-width" disabled={!!busy||command.physical_status==="awaiting_ide_approval"} onClick={()=>void work("Requesting operator approval…",async()=>setCommand(await post(route(projectId)+"/commands/"+command.id+"/request-physical")))}>{command.physical_status==="awaiting_ide_approval"?"Waiting for IDE operator approval":"Request a physical run"}</button>}
                  {!command.run_id ? (
                    <button
                      className="primary full-width"
                      disabled={
                        !!busy || !workspace.connected || !!workspace.active_run || command.status!=="ready"
                      }
                      onClick={() =>
                        void work("Starting simulation…", async () =>
                          setCommand(
                            await post(
                              route(projectId) +
                                "/commands/" +
                                command.id +
                                "/run",
                            ),
                          ),
                        )
                      }
                    >
                      Start simulation <ArrowRight size={18} />
                    </button>
                  ) : active ? (
                    <button
                      className="stop-command full-width"
                      disabled={run?.stop_requested}
                      onClick={() =>
                        void work("Requesting stop…", async () => {
                          await post(
                            route(projectId) +
                              "/commands/" +
                              command.id +
                              "/stop",
                          );
                          setNotice(
                            "Stop requested. Waiting for the simulator to confirm it has stopped.",
                          );
                        })
                      }
                    >
                      <Square size={16} />{" "}
                      {run?.stop_requested
                        ? "Stop requested"
                        : "Stop simulation"}
                    </button>
                  ) : (
                    <button
                      className="secondary full-width"
                      onClick={() => {
                        setCommand(null);
                        setRun(null);
                        setInput("");
                        void refresh();
                      }}
                    >
                      Give another command <ArrowRight size={18} />
                    </button>
                  )}
                </div>
              )}
              {workspace.active_run && workspace.active_run !== run?.id && (
                <div className="callout">
                  This workspace is currently in use. You can watch it here; new
                  commands become available when the current operation finishes.
                </div>
              )}
            </aside>
          </div>
          <section className="asset-section">
            <div className="asset-heading">
              <div>
                <span className="overline">KNOW YOUR WORKSPACE</span>
                <h2>Everything has a name.</h2>
                <p>Select an asset to find it in the workspace.</p>
              </div>
              <label className="asset-search">
                <Search size={18} />
                <input
                  aria-label="Find an asset"
                  placeholder="Find an asset…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
            </div>
            <div className="asset-grid">
              {assets
                .filter((a) =>
                  (a.name + " " + a.kind)
                    .toLowerCase()
                    .includes(search.toLowerCase()),
                )
                .map((a) => (
                  <button
                    className={`asset-card ${a.id === selected ? "selected" : ""}`}
                    key={a.id}
                    aria-label={`View asset ${a.name}`}
                    onClick={() => selectAsset(a)}
                  >
                    <span className={`asset-symbol ${a.kind}`}>
                      <Box size={23} />
                    </span>
                    <span>
                      <strong>{a.name}</strong>
                      <small>
                        {a.read_only
                          ? "Visual scene asset"
                          : a.kind === "object"
                            ? "Movable item"
                            : a.kind === "region"
                              ? "Destination area"
                              : "Support surface / obstacle"}
                      </small>
                    </span>
                    <ChevronRight size={17} />
                  </button>
                ))}
            </div>
            {!assets.length && (
              <p className="muted">
                No named assets are available in this workspace yet. Your
                operator can add them in RoboDE or Isaac Sim.
              </p>
            )}
          </section>
          <footer className="business-footer">
            <span>Shared planning engine. A simpler way to work.</span>
            <span>
              Commands run in simulation. Robot configuration stays in Robot
              IDE.
            </span>
          </footer>
        </main>
      )}
    </div>
  );
}

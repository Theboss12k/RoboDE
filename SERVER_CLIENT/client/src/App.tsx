import { version as appVersion } from "../package.json";
import Feedback from "./ui/Feedback";
import NvidiaLogo from "./branding/NvidiaLogo";
import RobotLogo from "./branding/RobotLogo";
import {useCloudActivity} from "./ui/useCloudActivity";
import {useDialogAccessibility} from "./ui/useDialogAccessibility";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Bot,
  Box,
  ChevronDown,
  Copy,
  ChevronRight,
  CircleHelp,
  FolderOpen,
  History,
  GitBranch,
  LoaderCircle,
  Plus,
  Square,
  X,
  PanelLeft,
  Settings,
} from "lucide-react";
import { api, post } from "./api";
import type {
  Health,
  Plan,
  PlanDefinition,
  Project,
  ProjectDetail,
  Run,
} from "./types";
import PlanWorkspace, { type PlanTab } from "./PlanWorkspace";
import RobotsWorkspace from "./RobotsWorkspace";
import Configuration from "./Configuration";
import type { LLMConfiguration, TaskDefinition } from "./types";
import EnvironmentWorkspace from "./EnvironmentWorkspace";
import Tutorial, { type TutorialLocation } from "./Tutorial";
type Workspace = "robots" | "environment" | "plans";

export default function App() {
  useDialogAccessibility();
  const [projectCopyNote, setProjectCopyNote] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(
    localStorage.getItem("robot-ide.project") || "apple_transfer",
  );
  const currentId = useRef(projectId);
  currentId.current = projectId;
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [llm, setLLM] = useState<LLMConfiguration>({
    adapters: [],
    default_id: null,
  });
  const [health, setHealth] = useState<Health | null>(null);
  useCloudActivity(!!health?.cloud_session);
  const [workspace, setWorkspace] = useState<Workspace>("plans");
  const [tab, setTab] = useState<PlanTab>("tasks");
  const [draft, setDraft] = useState<PlanDefinition | null>(null);
  const [dirty, setDirty] = useState(false);
  const [revision, setRevision] = useState<Plan | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sidebar, setSidebar] = useState(true);
  const [modal, setModal] = useState<
    "project" | "plan" | "connections" | "configuration" | null
  >(null);
  const [name, setName] = useState("");
  const [configurationTab, setConfigurationTab] = useState<"robots" | "llm">(
    "robots",
  );
  const [tutorial, setTutorial] = useState(false);
  const [tutorialWizard, setTutorialWizard] = useState<number | undefined>();
  const tourReturn = useRef({ workspace, tab, sidebar, modal });
  const running = !!run && !run.finished_at;
  const disabled = !!busy || running;
  const refreshSequence = useRef(0);
  const refresh = useCallback(async () => {
    const sequence=++refreshSequence.current;
    const id = currentId.current;
    const next = await api<ProjectDetail>(`/projects/${id}`);
    if (id === currentId.current && sequence===refreshSequence.current) setDetail(next);
    return next;
  }, []);
  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const loadLLM = () =>
    api<LLMConfiguration>("/llm/adapters")
      .then(setLLM)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void loadLLM();
  }, []);
  useEffect(() => {
    void Promise.all([api<Project[]>("/projects"), api<Health>("/health")])
      .then(([p, h]) => {
        setProjects(p);
        setHealth(h);
        if (!p.some((x) => x.id === currentId.current) && p.length)
          setProjectId(p[0].id);
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setDraft(null);
    setDirty(false);
    setRevision(null);
    setRun(null);
    setSelected(null);
    setError(null);
    setExpanded(new Set());
    localStorage.setItem("robot-ide.project", projectId);
    void api<ProjectDetail>(`/projects/${projectId}`)
      .then(async (data) => {
        if (cancelled) return;
        setDetail(data);
        const first = data.plan_definitions[0];
        if (first) {
          setDraft(first);
          setExpanded(new Set([first.id]));
          setSelected(first.tasks[0]?.id ?? null);
          if (first.latest_revision_id) {
            const p = await api<Plan>(
              `/projects/${projectId}/plans/${first.latest_revision_id}`,
            );
            if (!cancelled) setRevision(p);
          }
        }
        if (data.active_run) {
          const r = await api<Run>(`/runs/${data.active_run}`);
          const p = await api<Plan>(
            `/projects/${projectId}/plans/${r.plan_id}`,
          );
          const d = await api<PlanDefinition>(
            `/projects/${projectId}/plan-definitions/${p.definition_id ?? p.id}`,
          );
          if (!cancelled) {
            setRun(r);
            setRevision(p);
            setDraft(d);
            setTab("simulation");
          }
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);
  useEffect(() => {
    if (!run || run.finished_at) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<Run>(`/runs/${run.id}`);
        if (cancelled) return;
        setRun(next);
        if (next.finished_at) {
          await refresh();
          if (next.status === "FAILED" || next.status === "TIMED_OUT")
            setError(next.logs.at(-1)?.message ?? "Simulation failed");
        } else timer = setTimeout(poll, 180);
      } catch (e) {
        if (!cancelled) {
          setError((e as Error).message);
          timer = setTimeout(poll, 1000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [run?.id, run?.finished_at, refresh]);
  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(null), 6500);
      return () => clearTimeout(timer);
    }
  }, [notice]);
  const saveCurrent = async () => {
    if (!draft || !dirty) return draft;
    const saved = await api<PlanDefinition>(
      `/projects/${projectId}/plan-definitions/${draft.id}`,
      {
        method: "PUT",
        body: JSON.stringify({
          name: draft.name,
          goal: draft.goal,
          tasks: draft.tasks,
          version: draft.version,
        }),
      },
    );
    setDraft(saved);
    setDirty(false);
    await refresh();
    return saved;
  };
  const openPlan = async (id: string, taskId?: string) =>
    act("Loading plan", async () => {
      await saveCurrent();
      const d = await api<PlanDefinition>(
        `/projects/${projectId}/plan-definitions/${id}`,
      );
      const p = d.latest_revision_id
        ? await api<Plan>(
            `/projects/${projectId}/plans/${d.latest_revision_id}`,
          )
        : null;
      setDraft(d);
      setRevision(p);
      setDirty(false);
      setRun(null);
      setSelected(taskId ?? d.tasks[0]?.id ?? null);
      setWorkspace("plans");
      setTab("tasks");
      setExpanded((prev) => new Set([...prev, id]));
    });
  const openRun = async (id: string) =>
    act("Loading recorded revision", async () => {
      await saveCurrent();
      const r = await api<Run>(`/runs/${id}`);
      const p = await api<Plan>(`/projects/${projectId}/plans/${r.plan_id}`);
      const d = await api<PlanDefinition>(
        `/projects/${projectId}/plan-definitions/${p.definition_id ?? p.id}`,
      );
      setDraft(d);
      setRevision(p);
      setDirty(false);
      setRun(r);
      setWorkspace("plans");
      setTab("simulation");
    });
  const stop = () => {
    if (run)
      void post<Run>(`/runs/${run.id}/stop`)
        .then(setRun)
        .catch((e) => setError(e.message));
  };
  const openTutorial = () => {
    tourReturn.current = { workspace, tab, sidebar, modal };
    setSidebar(true);
    setModal(null);
    setTutorial(true);
  };
  const closeTutorial = () => {
    setTutorial(false);
    setTutorialWizard(undefined);
    setWorkspace(tourReturn.current.workspace);
    setTab(tourReturn.current.tab);
    setSidebar(tourReturn.current.sidebar);
    setModal(tourReturn.current.modal);
  };
  const navigateTutorial = useCallback((location: TutorialLocation) => {
    if (location.configuration) setConfigurationTab(location.configuration);
    if (location.workspace) setWorkspace(location.workspace);
    if (location.planTab) setTab(location.planTab);
    setTutorialWizard(location.wizardStage);
    setModal(
      location.configuration
        ? "configuration"
        : location.connections
          ? "connections"
          : null,
    );
  }, []);
  const newDialog = (kind: "plan" | "project") => {
    setName("");
    setModal(kind);
  };
  const definitions = detail?.plan_definitions ?? [];
  return (
    <div className={`ide ide-v3 ${sidebar ? "" : "collapsed"}`}>
      <header className="titlebar">
        <div className="brand">
          <span className="brand-mark">
            <RobotLogo />
          </span>
          <strong>
            Robo<span>DE</span>
          </strong>
          <span className="version">{appVersion}</span>
        </div>
        <div className="title-crumb">
          <FolderOpen size={13} />
          <span>{detail?.project.name ?? "Workspace"}</span>
          <ChevronRight size={12} />
          <b>{workspace[0].toUpperCase() + workspace.slice(1)}</b>
        </div>
        {running && (
          <button className="stop-button global-stop" onClick={stop}>
            <Square size={12} />
            {run.stop_requested ? "Stopping…" : "Stop simulation"}
          </button>
        )}
        <button
          className="connection-button"
          onClick={() => setModal("connections")}
        >
          <span className={`status-dot ${health ? "green" : ""}`} />
          {health ? "Runtime connected" : "Connecting…"}
        </button>
        <button
          className="configuration-launch"
          aria-label="Open configuration"
          onClick={() => setModal("configuration")}
        >
          <Settings size={14} /> Configuration
        </button>
        <button
          className="tutorial-launch"
          aria-label="Open tutorial"
          onClick={openTutorial}
        >
          <BookOpen size={13} /> Tutorial
        </button>
      </header>
      <nav className="activity-bar" aria-label="Workspace navigation">
        <button
          aria-label="Toggle project explorer"
          aria-expanded={sidebar}
          title="Toggle project explorer"
          onClick={() => setSidebar(!sidebar)}
        >
          <PanelLeft size={20} />
        </button>
        {(
          [
            { id: "robots", icon: Bot, label: "Robots" },
            { id: "environment", icon: Box, label: "Environment" },
            { id: "plans", icon: GitBranch, label: "Plans" },
          ] as const
        ).map((w) => (
          <button
            key={w.id}
            aria-label={`Open ${w.label}`}
            title={w.label}
            className={workspace === w.id ? "active" : ""}
            aria-current={workspace === w.id ? "page" : undefined}
            onClick={() => setWorkspace(w.id)}
          >
            <w.icon size={20} />
          </button>
        ))}
        <div className="activity-spacer" />
        <button aria-label="Open tutorial help" onClick={openTutorial}>
          <CircleHelp size={20} />
        </button>
      </nav>
      {sidebar && (
        <aside className="explorer">
          <div className="panel-heading">
            <span>PROJECT EXPLORER</span>
            <button
              aria-label="New project"
              disabled={disabled || !detail}
              onClick={() => newDialog("project")}
            >
              <Plus size={14} />
            </button>
          </div>
          <div className="project-selector">
            <FolderOpen size={15} />
            <select
              aria-label="Select project"
              disabled={disabled}
              value={projectId}
              onChange={(e) => {
                const id = e.target.value;
                void act("Switching project", async () => {
                  await saveCurrent();
                  setProjectCopyNote("");
                  setProjectId(id);
                });
              }}
            >
              {projects.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <ChevronDown size={12} />
          </div>
          {detail && <div className="project-id-row">
            <label htmlFor="project-id-value">Project ID</label>
            <div><input id="project-id-value" aria-label="Project ID" readOnly value={detail.project.id}
              onFocus={(e) => e.target.select()} />
              <button aria-label="Copy project ID" title="Copy project ID" onClick={async () => {
                try { await navigator.clipboard.writeText(detail.project.id); setProjectCopyNote("Copied"); }
                catch { setProjectCopyNote("Select the ID and copy it"); }
              }}><Copy size={12}/></button></div>
            {projectCopyNote && <small role="status">{projectCopyNote}</small>}
          </div>}
          <div className="project-hierarchy">
            <div className="tree-label">
              <ChevronDown size={12} />
              <strong>{detail?.project.name ?? "Project"}</strong>
            </div>
            <div className="tree-label plans-tree-heading">
              <ChevronDown size={12} />
              <span>PLANS</span>
              <small>{definitions.length}</small>
              <button
                aria-label="New plan"
                disabled={disabled || !detail}
                onClick={() => newDialog("plan")}
              >
                <Plus size={13} />
              </button>
            </div>
            {definitions.map((p) => (
              <div className="plan-tree" key={p.id}>
                <div
                  className={`plan-tree-heading ${draft?.id === p.id ? "selected" : ""}`}
                >
                  <button
                    className="tree-toggle"
                    aria-label={`Toggle tasks for ${p.name}`}
                    aria-expanded={expanded.has(p.id)}
                    onClick={() =>
                      setExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(p.id)) next.delete(p.id);
                        else next.add(p.id);
                        return next;
                      })
                    }
                  >
                    {expanded.has(p.id) ? (
                      <ChevronDown size={12} />
                    ) : (
                      <ChevronRight size={12} />
                    )}
                  </button>
                  <button
                    disabled={disabled}
                    onClick={() => void openPlan(p.id)}
                  >
                    <GitBranch size={13} />
                    <span title={p.name}>
                      {p.id === draft?.id ? draft.name : p.name}
                    </span>
                    <small>
                      {(p.id === draft?.id ? draft : p).tasks.length}
                    </small>
                  </button>
                </div>
                {expanded.has(p.id) && (
                  <div className="task-tree">
                    {(p.id === draft?.id ? draft : p).tasks.map((t) => (
                      <button
                        key={t.id}
                        disabled={disabled}
                        className={
                          draft?.id === p.id && selected === t.id
                            ? "selected"
                            : ""
                        }
                        onClick={() => {
                          if (draft?.id === p.id) {
                            setSelected(t.id);
                            setWorkspace("plans");
                            setTab("tasks");
                          } else void openPlan(p.id, t.id);
                        }}
                      >
                        <span className="task-bullet" />
                        <span>{t.name}</span>
                        <small>{t.robot_id}</small>
                      </button>
                    ))}
                    {!p.tasks.length && (
                      <span className="tree-empty">
                        Add tasks inside this plan.
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
            {!definitions.length && (
              <div className="tree-empty">
                Create a plan, then add its tasks.
              </div>
            )}
          </div>
          <div className="explorer-reference">
            <button
              disabled={disabled}
              onClick={() =>
                void act("Opening project history", async () => {
                  await saveCurrent();
                  setDraft(null);
                  setDirty(false);
                  setRevision(null);
                  setRun(null);
                  setWorkspace("plans");
                  setTab("history");
                })
              }
            >
              <History size={14} />
              <span>Project run history</span>
            </button>
            <button onClick={() => setWorkspace("robots")}>
              <Bot size={14} />
              <span>Robots</span>
              <small>{detail?.robots.length ?? 0}</small>
            </button>
            <button onClick={() => setWorkspace("environment")}>
              <Box size={14} />
              <span>Environment</span>
              <small>{detail?.objects.length ?? 0} objects</small>
            </button>
          </div>
          <div className="explorer-bottom">
            <span className="eyebrow">A CLEAR HIERARCHY</span>
            <p>Project → Plans → Tasks</p>
            <small>
              Robot configuration and the environment are shared project
              resources.
            </small>
          </div>
        </aside>
      )}
      <main className="main">
        <nav className="workspace-switcher" aria-label="Main workspaces">
          {(
            [
              {
                id: "robots",
                name: "Robots",
                description: "Models, instances & adapters",
                icon: Bot,
              },
              {
                id: "environment",
                name: "Environment",
                description: "Simulator, objects & placement",
                icon: Box,
              },
              {
                id: "plans",
                name: "Plans",
                description: "Goals, tasks & execution",
                icon: GitBranch,
              },
            ] as const
          ).map((w) => (
            <button
              key={w.id}
              aria-label={`${w.name} workspace`}
              aria-current={workspace === w.id ? "page" : undefined}
              className={workspace === w.id ? "active" : ""}
              onClick={() => setWorkspace(w.id)}
            >
              <w.icon size={17} />
              <span>
                <strong>{w.name}</strong>
                <small>{w.description}</small>
              </span>
              <span className="workspace-count" aria-hidden="true">
                {w.id === "robots" ? detail?.robots.length ?? "—" : w.id === "environment" ? detail?.objects.length ?? "—" : definitions.length}
              </span>
            </button>
          ))}
          <span className="workspace-spacer" />
          {busy && (
            <span className="busy-status">
              <LoaderCircle size={13} className="spin" />
              {busy}
            </span>
          )}
        </nav>
        <Feedback message={error} className="alert error" onDismiss={() => setError(null)} />
        <Feedback message={notice} kind="success" className="alert notice" onDismiss={() => setNotice(null)} />
        {health?.cloud_session && <div className="cloud-session-note" role="note">Cloud session · stops after 10 minutes without activity · maximum 2 hours per start. Save your edits before leaving.</div>}
        <div className="workspace-surface">
          {!detail ? (
            <div className="workspace-empty">
              <LoaderCircle size={27} className="spin" />
              <h2>Loading project…</h2>
              <button
                className="secondary"
                disabled={!!busy}
                onClick={() =>
                  void act("Reconnecting", async () => {
                    await api(`/projects/${projectId}/simulation`, {
                      method: "PUT",
                      body: JSON.stringify({ adapter: "mock" }),
                    });
                    await refresh();
                  })
                }
              >
                Connect built-in simulator
              </button>
            </div>
          ) : workspace === "robots" ? (
            <RobotsWorkspace
              key={projectId}
              detail={detail}
              busy={disabled}
              tutorialWizard={tutorialWizard}
              onError={setError}
              onRefresh={async () => {
                await refresh();
              }}
              onInitial={(id, q) =>
                void act("Saving robot configuration", async () => {
                  await api(`/projects/${projectId}/initial`, {
                    method: "PUT",
                    body: JSON.stringify({ robot_id: id, positions: q }),
                  });
                  await refresh();
                  setNotice(
                    "Saved initial configuration. Actual simulation state is unchanged.",
                  );
                })
              }
              onModel={(id, actuators, capabilities) =>
                void act("Saving reusable model", async () => {
                  const existing = detail.robots.find(
                    (r) => r.model.robot.id === id,
                  )!.model;
                  await api(`/registry/${id}/configuration`, {
                    method: "PUT",
                    body: JSON.stringify({
                      actuators,
                      capabilities: {
                        ...existing.capabilities,
                        ...capabilities,
                      },
                    }),
                  });
                  await refresh();
                  setNotice(
                    "Reusable model updated. Recompile affected plans and regenerate affected adapters.",
                  );
                })
              }
            />
          ) : workspace === "environment" ? (
            <EnvironmentWorkspace
              onRefresh={async () => {
                await refresh();
              }}
              detail={detail}
              busy={disabled}
              onBackend={(adapter, objects) =>
                void act(
                  adapter === detail.adapter
                    ? "Connecting simulator"
                    : "Starting simulator and transferring scene",
                  async () => {
                    if (objects)
                      await api(`/projects/${projectId}/world`, {
                        method: "PUT",
                        body: JSON.stringify({ objects }),
                      });
                    const result = await api<{
                      scene_transferred: boolean;
                      robots: number;
                      objects: number;
                      warning?: string;
                    }>(`/projects/${projectId}/simulation`, {
                      method: "PUT",
                      body: JSON.stringify({ adapter }),
                    });
                    await refresh();
                    setNotice(
                      result.warning ||
                        (result.scene_transferred
                          ? `Scene transferred · ${result.robots} robots and ${result.objects} objects. Current poses preserved; saved starting points unchanged.`
                          : "Simulator connected. Current state read."),
                    );
                  },
                )
              }
              onReset={() =>
                void act("Resetting simulator", async () => {
                  await post(`/projects/${projectId}/reset`);
                  setRun(null);
                  await refresh();
                  setNotice(
                    "Simulator reset to the saved initial configuration and scene. Recompile before execution.",
                  );
                })
              }
              onDisconnect={() =>
                void act("Disconnecting simulator", async () => {
                  await post(`/projects/${projectId}/disconnect`);
                  await refresh();
                  setNotice(
                    "Simulator disconnected. Connect explicitly to resume.",
                  );
                })
              }
              onWorld={(objects) =>
                void act("Saving environment", async () => {
                  await api(`/projects/${projectId}/world`, {
                    method: "PUT",
                    body: JSON.stringify({ objects }),
                  });
                  await refresh();
                  setNotice("Environment saved. Recompile affected plans.");
                })
              }
            />
          ) : (
            <PlanWorkspace
              detail={detail}
              draft={draft}
              revision={revision}
              run={run}
              tab={tab}
              selected={selected}
              busy={disabled}
              dirty={dirty}
              onTab={setTab}
              onSelect={setSelected}
              onChange={(p) => {
                setDraft(p);
                setDirty(true);
              }}
              onNew={() => newDialog("plan")}
              onArchive={() =>
                void act("Archiving plan", async () => {
                  if (!draft) return;
                  await saveCurrent();
                  await api(
                    `/projects/${projectId}/plan-definitions/${draft.id}`,
                    { method: "DELETE" },
                  );
                  setDraft(null);
                  setDirty(false);
                  setRevision(null);
                  setRun(null);
                  setTab("history");
                  await refresh();
                  setNotice(
                    "Plan archived. Its revisions and results remain available in project run history.",
                  );
                })
              }
              onSave={() =>
                void act("Saving plan", async () => {
                  await saveCurrent();
                  setNotice(
                    "Plan saved. Compile to create a new execution revision.",
                  );
                })
              }
              llm={llm}
              onRefine={(taskId, instruction) =>
                void act("Drafting task refinement", async () => {
                  const saved = await saveCurrent();
                  if (!saved) return;
                  const task = saved.tasks.find((t) => t.id === taskId);
                  const result = await post<{ task: TaskDefinition }>(
                    `/projects/${projectId}/plan-definitions/${saved.id}/tasks/${taskId}/refine`,
                    {
                      version: saved.version,
                      instruction,
                      adapter_id: task?.llm_adapter_id,
                    },
                  );
                  setDraft({
                    ...saved,
                    tasks: saved.tasks.map((t) =>
                      t.id === taskId ? result.task : t,
                    ),
                  });
                  setDirty(true);
                  setNotice(
                    "Task proposal ready. Review it, then save and compile.",
                  );
                })
              }
              onDraft={(goals, adapter_id) =>
                void act("Generating atomic tasks", async () => {
                  const saved = await saveCurrent();
                  if (!saved) return;
                  const d = await post<PlanDefinition>(
                    `/projects/${projectId}/plan-definitions/${saved.id}/draft`,
                    { goals, version: saved.version, adapter_id },
                  );
                  setDraft(d);
                  setDirty(false);
                  setSelected(d.tasks[0]?.id ?? null);
                  setRun(null);
                  await refresh();
                  setNotice(
                    "Atomic tasks generated. Review assignments and parameters, then compile the plan.",
                  );
                })
              }
              onCompile={() =>
                void act("Compiling plan", async () => {
                  const saved = await saveCurrent();
                  if (!saved) return;
                  const p = await post<Plan>(
                    `/projects/${projectId}/plan-definitions/${saved.id}/compile`,
                  );
                  setRevision(p);
                  setRun(null);
                  setDraft(
                    await api(
                      `/projects/${projectId}/plan-definitions/${saved.id}`,
                    ),
                  );
                  await refresh();
                  if (!p.valid)
                    setError(
                      "Compilation found failed validation checks. Review them before simulation.",
                    );
                })
              }
              onSimulate={() =>
                void act("Starting simulation", async () => {
                  if (!revision) return;
                  const r = await post<Run>(
                    `/projects/${projectId}/plans/${revision.id}/simulate`,
                    {
                      fingerprint: revision.fingerprint,
                      adapter: detail.adapter,
                    },
                  );
                  setRun(r);
                  setTab("simulation");
                })
              }
              onStop={stop}
              onRun={(id) => void openRun(id)}
            />
          )}
        </div>
      </main>
      <footer className="statusbar">
        <span>
          <span className={`status-dot ${detail ? "green" : ""}`} />{" "}
          {detail?.project.name ?? projectId}
        </span>
        <span>
          {workspace === "plans"
            ? "Project → Plans → Tasks"
            : workspace === "robots"
              ? "Reusable robot configuration"
              : "Project environment"}
        </span>
        <span>
          {detail?.adapter === "isaac_sim" ? (
            <>
              <NvidiaLogo /> Isaac Sim
            </>
          ) : (
            "Built-in simulator"
          )}{" "}
          · {detail?.robots.length ?? 0} robots
        </span>
        <span className="status-spacer" />
        <span>Automatic execution: simulation only</span>
      </footer>
      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) {
              // Use the dialog's close action, including its busy/session guard.
              const dialogs=e.currentTarget.querySelectorAll<HTMLElement>('[role="dialog"]');
              dialogs[dialogs.length-1]?.querySelector<HTMLButtonElement>('button[aria-label^="Close"]:not(:disabled)')?.click();
            }
          }}
        >
          {modal === "configuration" ? (
            <Configuration
              initialTab={configurationTab}
              detail={detail}
              disabled={disabled}
              onClose={() => {setModal(null); void refresh();}}
              onChanged={() => {
                void loadLLM();
                void refresh();
              }}
              onAdded={() => {
                void refresh();
              }}
            />
          ) : modal === "connections" ? (
            <div
              className="modal connections-modal"
              role="dialog"
              aria-modal="true"
              aria-label="Runtime and integrations"
            >
              <div className="section-toolbar">
                <h2>Runtime & integrations</h2>
                <button
                  aria-label="Close integrations"
                  onClick={() => setModal(null)}
                >
                  <X size={16} />
                </button>
              </div>
              <p>Runtime: {health?.status ?? "unavailable"}</p>
              <p>Task provider: {health?.provider ?? "unavailable"}</p>
              <p>
                Simulator:{" "}
                {detail?.adapter === "isaac_sim" ? (
                  <span className="nvidia-tool-heading">
                    <NvidiaLogo />
                    Isaac Sim worker
                  </span>
                ) : (
                  "Built-in kinematic preview"
                )}
              </p>
              <p>
                Adapter generation: templates plus configured AI for SDK drafts.
              </p>
              <p>
                ROS 2 live manual control: separate authenticated bridge,
                reviewed adapter, connection validation and explicit arming.
              </p>
              <small>
                Use Configuration → LLM adapters for task and SDK drafting.
                Native Isaac GPU execution and real hardware need their own
                acceptance checks.
              </small>
            </div>
          ) : (
            <form
              className="modal"
              role="dialog"
              aria-modal="true"
              aria-label={modal === "plan" ? "New plan" : "New project"}
              onSubmit={(e) => {
                e.preventDefault();
                const kind = modal;
                void act(
                  kind === "plan" ? "Creating plan" : "Creating project",
                  async () => {
                    await saveCurrent();
                    if (kind === "plan") {
                      const d = await post<PlanDefinition>(
                        `/projects/${projectId}/plan-definitions`,
                        {
                          name: name.trim(),
                          goal: detail?.project.default_prompt ?? "",
                        },
                      );
                      setDraft(d);
                      setDirty(false);
                      setRevision(null);
                      setRun(null);
                      setSelected(null);
                      setExpanded((prev) => new Set([...prev, d.id]));
                      setWorkspace("plans");
                      setTab("tasks");
                      await refresh();
                    } else {
                      const p = await post<Project>("/projects", {
                        name: name.trim(),
                        source: projectId,
                      });
                      setProjects(await api("/projects"));
                      setProjectId(p.id);
                    }
                    setModal(null);
                  },
                );
              }}
            >
              <div className="section-toolbar">
                <h2>
                  {modal === "plan" ? "Create a plan" : "Create a project"}
                </h2>
                <button
                  type="button"
                  aria-label="Close dialog"
                  disabled={!!busy}
                  onClick={() => setModal(null)}
                >
                  <X size={16} />
                </button>
              </div>
              <label className="field">
                Name
                <input
                  aria-label={
                    modal === "plan" ? "New plan name" : "New project name"
                  }
                  autoFocus
                  required
                  maxLength={modal === "plan" ? 120 : 80}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <p>
                {modal === "plan"
                  ? "Add atomic tasks manually or generate them from robot goals."
                  : "The new project references shared robot models and copies this project’s saved instances and environment."}
              </p>
              <button
                className="primary"
                type="submit"
                disabled={disabled || !name.trim()}
              >
                <Plus size={14} /> Create {modal}
              </button>
            </form>
          )}
        </div>
      )}
      {tutorial && (
        <Tutorial
          onClose={closeTutorial}
          onNavigate={navigateTutorial}
          onStop={stop}
          running={running}
          layoutKey={`${workspace}-${tab}-${modal}-${tutorialWizard}-${detail?.project.id}`}
        />
      )}
    </div>
  );
}

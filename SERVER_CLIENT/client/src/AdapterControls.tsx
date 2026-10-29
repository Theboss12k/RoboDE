import Feedback from "./ui/Feedback";
import NvidiaLogo from "./branding/NvidiaLogo";
import StandardTaskEditor from "./StandardTaskEditor";
import type { StandardCommand } from "./types";
import { useEffect, useRef, useState } from "react";
import {
  Gamepad2,
  Minus,
  Plus,
  Plug,
  ShieldCheck,
  Square,
  Unplug,
} from "lucide-react";
import type {
  AdapterBundle,
  CellRobot,
  ControlSession,
  ProjectDetail,
  ConnectionProfile,
} from "./types";
import { api, post } from "./api";
import Scene from "./Scene";
import CommandTester from "./CommandTester";
import { useControlStream } from "./useControlStream";
export default function AdapterControls({
  detail,
  robot,
  adapter,
  onEnvironmentChanged,
  onSessionChange,
  initialMode = "test",
  testOnly = false,
  autoConnect = false,
  globalModelId,
}: {
  detail: ProjectDetail;
  robot: CellRobot;
  adapter: string | AdapterBundle;
  onEnvironmentChanged: () => void;
  onSessionChange?: (active: boolean, sessionId?: string) => void;
  initialMode?: ControlSession["mode"];
  testOnly?: boolean;
  autoConnect?: boolean;
  globalModelId?: string;
}) {
  const manualAvailable = !testOnly || !!globalModelId;
  const adapterId = typeof adapter === "string" ? adapter : adapter.id;
  const category = typeof adapter === "string" ? "virtual" : adapter.category;
  const [standard, setStandard] = useState<StandardCommand>(() => {
    const target = Object.keys(robot.model.actuators.actuators)[0];
    return {
      type: "SET_ACTUATOR",
      target,
      value: robot.state.positions[target],
      unit: robot.model.actuators.actuators[target].unit as "rad" | "m",
    };
  });
  const [mode, setMode] = useState<ControlSession["mode"]>(initialMode);
  const [session, setSession] = useState<ControlSession | null>(null);
  const [targets, setTargets] = useState(robot.state.positions);
  const [profiles, setProfiles] = useState<ConnectionProfile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [profileName, setProfileName] = useState("Robot connection");
  const [bridgeUrl, setBridgeUrl] = useState(
    typeof adapter === "string"
      ? ""
      : (adapter.connection.bridge_url ?? "http://127.0.0.1:8767"),
  );
  const [tokenEnv, setTokenEnv] = useState(
    typeof adapter === "string"
      ? "ROS_BRIDGE_TOKEN"
      : (adapter.connection.token_env ?? "ROS_BRIDGE_TOKEN"),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const sessionRef = useRef<ControlSession | null>(null);
  const busyRef = useRef(false);
  const polling = useRef(false);
  const targetRef = useRef(targets);
  targetRef.current = targets;
  const motion = useControlStream<Record<string, number>, ControlSession>({
    scope: session?.id ?? null,
    enabled:
      !!session &&
      mode !== "live" &&
      !busy &&
      session.command_run?.status !== "running",
    send: (positions) =>
      post<ControlSession>(`/controls/${sessionRef.current!.id}/command`, {
        positions,
      }),
    onFeedback: (s) => {
      sessionRef.current = s;
      setSession(s);
    },
    onError: (e) => setError(e.message),
  });
  useEffect(() => {
    if(globalModelId){setProfiles([]);return;}
    void api<ConnectionProfile[]>(
      `/projects/${detail.project.id}/robots/${robot.instance.instance.id}/connections`,
    )
      .then((all) => {
        const relevant = all.filter((p) => p.adapter_id === adapterId);
        setProfiles(relevant);
        if (relevant.length) {
          setProfileId(relevant[0].id);
          setProfileName(relevant[0].name);
          setBridgeUrl(relevant[0].connection.bridge_url ?? "");
          setTokenEnv(relevant[0].connection.token_env ?? "ROS_BRIDGE_TOKEN");
        }
      })
      .catch((e) => setError(e.message));
  }, [detail.project.id, robot.instance.instance.id, adapterId]);
  sessionRef.current = session;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const current = sessionRef.current;
      if (current)
        void api(`/controls/${current.id}`, { method: "DELETE" }).catch(
          () => {},
        );
      onSessionChange?.(false);
    };
  }, []);
  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    const timer = setInterval(
      async () => {
        if (polling.current) return;
        const monitoring =
          mode === "environment" && (busyRef.current || motion.active.current);
        if (!monitoring && (busyRef.current || motion.active.current)) return;
        const revision = motion.revision.current;
        polling.current = true;
        try {
          if (monitoring) {
            // Command execution holds the control lock. Read observed project
            // state so the preview moves during the trajectory, not just at its end.
            const state = await api<ProjectDetail>(
              `/projects/${detail.project.id}`,
            );
            const measured = state.robots.find(
              (r) => r.instance.instance.id === robot.instance.instance.id,
            )?.state;
            if (measured && !cancelled && revision === motion.revision.current)
              setSession((s) =>
                s?.id === session.id &&
                Date.parse(measured.measured_at) >=
                  Date.parse(s.feedback.measured_at)
                  ? {
                      ...s,
                      feedback: { ...s.feedback, ...measured },
                      stopped_verified: false,
                    }
                  : s,
              );
          } else {
            const s = await api<ControlSession>(`/controls/${session.id}`);
            if (
              !cancelled &&
              revision === motion.revision.current &&
              !motion.active.current
            )
              setSession(s);
          }
        } catch (e) {
          if (!cancelled && revision === motion.revision.current) {
            motion.cancel();
            setError((e as Error).message);
            setSession((s) =>
              s ? { ...s, armed: false, connection_validated: false } : s,
            );
          }
        } finally {
          polling.current = false;
        }
      },
      mode === "live" ? 1000 : 100,
    );
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [session?.id, mode]);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    busyRef.current = true;
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  };
  const open = () =>
    work(async () => {
      const s = await post<ControlSession>(
        globalModelId ? `/library/robots/${globalModelId}/controls` : `/projects/${detail.project.id}/controls`,
        {
          ...(globalModelId ? {category} : {robot_id: robot.instance.instance.id}),
          adapter_id: adapterId,
          ...(!globalModelId ? {mode,profile_id: profileId || null} : {}),
        },
      );
      if (!mounted.current) {
        await api(`/controls/${s.id}`, { method: "DELETE" });
        return;
      }
      sessionRef.current = s;
      setSession(s);
      setTargets(s.feedback.positions);
      onSessionChange?.(true,s.id);
    });
  const close = () =>
    work(async () => {
      motion.cancel();
      if (session) await api(`/controls/${session.id}`, { method: "DELETE" });
      setSession(null);
      onSessionChange?.(false);
      if (mode === "environment") onEnvironmentChanged();
    });
  const command = (q: Record<string, number>) => {
    if (mode !== "live") {
      setError(null);
      targetRef.current = q;
      setTargets(q);
      motion.enqueue(q);
      return;
    }
    return work(async () => {
      if (!session) return;
      const s = await post<ControlSession>(`/controls/${session.id}/command`, {
        positions: q,
      });
      setSession(s);
      setTargets(s.feedback.positions);
    });
  };
  const updateTarget = (key: string, value: number) => {
    if (!Number.isFinite(value)) return;
    const q = { ...targetRef.current, [key]: value };
    targetRef.current = q;
    setTargets(q);
    if (
      mode !== "live" &&
      Object.entries(robot.model.actuators.actuators).every(
        ([k, a]) => Number.isFinite(q[k]) && q[k] >= a.min && q[k] <= a.max,
      )
    )
      command(q);
  };
  useEffect(() => {
    if (!autoConnect) return;
    const timer = setTimeout(() => void open(), 0);
    return () => clearTimeout(timer);
  }, [autoConnect, adapterId]);
  const canAdjust =
    !!session &&
    !busy &&
    session.command_run?.status !== "running" &&
    (mode !== "live" || session.armed);
  const canCommand = canAdjust && !motion.busy;
  const displayed = session
    ? { ...robot, state: { ...robot.state, ...session.feedback } }
    : robot;
  return (
    <section className="adapter-controls" aria-busy={busy || motion.busy}>
      <div className="section-toolbar">
        <div>
          <span className="eyebrow">ADAPTER / CONTROLS</span>
          <h2 className="nvidia-tool-heading">
            {(
              typeof adapter === "string"
                ? adapter === "isaac_sim"
                : adapter.kind === "isaac_sim"
            ) ? (
              <NvidiaLogo />
            ) : (
              <Gamepad2 size={20} />
            )}{" "}
            {typeof adapter === "string"
              ? adapter === "mock"
                ? "Built-in simulator"
                : "NVIDIA Isaac Sim"
              : adapter.name}
          </h2>
        </div>
        <span className="tiny-tag">{category}</span>
      </div>
      {category === "physical" && !testOnly && (
        <details className="connection-profile-editor">
          <summary>Instance connection profiles</summary>
          <label className="field">
            Saved profile
            <select
              aria-label="Connection profile"
              value={profileId}
              disabled={!!session || busy}
              onChange={(e) => {
                setProfileId(e.target.value);
                const p = profiles.find((x) => x.id === e.target.value);
                if (p) {
                  setProfileName(p.name);
                  setBridgeUrl(p.connection.bridge_url ?? "");
                  setTokenEnv(p.connection.token_env ?? "ROS_BRIDGE_TOKEN");
                }
              }}
            >
              <option value="">Adapter defaults / new profile</option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          {typeof adapter !== "string" && adapter.kind === "ros2" && (
            <>
              <label className="field">
                Profile name
                <input
                  aria-label="Connection profile name"
                  value={profileName}
                  disabled={!!session || busy}
                  onChange={(e) => setProfileName(e.target.value)}
                />
              </label>
              <label className="field">
                Bridge URL
                <input
                  aria-label="Profile bridge URL"
                  value={bridgeUrl}
                  disabled={!!session || busy}
                  onChange={(e) => setBridgeUrl(e.target.value)}
                />
              </label>
              <label className="field">
                Token environment variable
                <input
                  aria-label="Profile token environment variable"
                  value={tokenEnv}
                  disabled={!!session || busy}
                  onChange={(e) => setTokenEnv(e.target.value)}
                />
              </label>
              <button
                className="secondary"
                disabled={!!session || busy}
                onClick={() =>
                  void work(async () => {
                    const path = `/projects/${detail.project.id}/robots/${robot.instance.instance.id}/connections`;
                    const data = {
                      name: profileName,
                      adapter_id: adapterId,
                      connection: {
                        bridge_url: bridgeUrl,
                        token_env: tokenEnv,
                      },
                    };
                    const p = profileId
                      ? await api<ConnectionProfile>(`${path}/${profileId}`, {
                          method: "PUT",
                          body: JSON.stringify(data),
                        })
                      : await post<ConnectionProfile>(path, data);
                    setProfiles((old) => [
                      p,
                      ...old.filter((x) => x.id !== p.id),
                    ]);
                    setProfileId(p.id);
                  })
                }
              >
                Save connection profile
              </button>
            </>
          )}
        </details>
      )}
      <div className="controls-toolbar">
        <label className="field">
          Control target
          <select
            aria-label="Control target"
            value={mode}
            disabled={testOnly || !!session || busy}
            onChange={(e) => setMode(e.target.value as ControlSession["mode"])}
          >
            <option value="test">Simulated adapter test</option>
            {category === "virtual" && !testOnly && (
              <option value="environment">Connected project simulator</option>
            )}
            {category === "physical" &&
              !testOnly &&
              typeof adapter !== "string" &&
              adapter.kind === "ros2" && (
                <option value="live">
                  Physical robot · live manual control
                </option>
              )}
          </select>
        </label>
        {session ? (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void close()}
          >
            <Unplug size={13} /> Disconnect controls
          </button>
        ) : (
          <button
            className="primary"
            disabled={busy}
            onClick={() => void open()}
          >
            <Plug size={13} />{" "}
            {mode === "live" ? "Connect physical robot" : "Connect controls"}
          </button>
        )}
        <button
          className="stop-button"
          disabled={!session}
          onClick={() => {
            motion.cancel();
            const id = session!.id;
            void post<ControlSession>(`/controls/${id}/stop`)
              .then((s) => {
                if (!mounted.current || sessionRef.current?.id !== id) return;
                setSession(s);
                setTargets(s.feedback.positions);
              })
              .catch((e) => setError(e.message));
          }}
        >
          <Square size={13} /> Stop
        </button>
      </div>
      <p className="control-source">
        {mode === "test"
          ? "SIMULATED FEEDBACK · Injected test transport · No physical connection"
          : mode === "environment"
            ? `PROJECT SIMULATOR · ${detail.adapter === "mock" ? "Built-in kinematic preview" : "Isaac Sim physics worker"}`
            : "HARDWARE FEEDBACK · Explicit arming required · Bounded manual increments"}
      </p>
      {mode !== "live" && manualAvailable && (
        <p className="preview-simulation-note">
          Joint controls update the simulator continuously as you adjust them.
        </p>
      )}
      <Feedback message={error} />
      {mode === "live" && (
        <div className="live-controls">
          <button
            className="secondary"
            disabled={!session || busy}
            onClick={() =>
              void work(async () =>
                setSession(await post(`/controls/${session!.id}/validate`)),
              )
            }
          >
            <ShieldCheck size={13} /> Validate connection & stop
          </button>
          <button
            className={session?.armed ? "stop-button" : "primary"}
            disabled={!session?.connection_validated || busy}
            onClick={() =>
              void work(async () =>
                setSession(
                  await post(
                    `/controls/${session!.id}/${session?.armed ? "stop" : "arm"}`,
                  ),
                ),
              )
            }
          >
            {session?.armed ? "Disarm" : "Arm live controls for 30s"}
          </button>
          <small>
            {session?.armed ? "ARMED" : "DISARMED"} · Maximum increment 0.15 rad
            / 0.01 m
          </small>
        </div>
      )}
      <div className="controls-layout">
        <div>
          {typeof adapter !== "string" && !!adapter.commands?.length && (
            <CommandTester
              adapter={adapter}
              session={session}
              busy={busy || motion.busy}
              onRun={(command_id, arguments_) =>
                void work(async () => {
                  if (session)
                    setSession(
                      await post(`/controls/${session.id}/named-command`, {
                        command_id,
                        arguments: arguments_,
                      }),
                    );
                })
              }
            />
          )}
          {manualAvailable && (
            <>
              <details className="standard-control">
                <summary>Standardized task controls</summary>
                <StandardTaskEditor
                  model={robot.model}
                  command={standard}
                  onChange={setStandard}
                  disabled={!canCommand}
                />
                <button
                  disabled={!canCommand}
                  onClick={() =>
                    void work(async () => {
                      if (!session) return;
                      const result = await post<ControlSession>(
                        `/controls/${session.id}/standard-command`,
                        standard,
                      );
                      setSession(result);
                      setTargets(result.feedback.positions);
                    })
                  }
                >
                  Run standardized task
                </button>
              </details>
              <div className="manual-joints">
                {Object.entries(robot.model.actuators.actuators).map(
                  ([key, a]) => (
                    <div className="manual-joint" key={key}>
                      <label>
                        <strong>{key === "gripper" ? "Gripper" : key}</strong>
                        <small>
                          {a.min} … {a.max} {a.unit}
                        </small>
                      </label>
                      <button
                        aria-label={`Decrease ${key}`}
                        disabled={!canAdjust}
                        onClick={() =>
                          void command({
                            ...targetRef.current,
                            [key]: Math.max(
                              a.min,
                              targetRef.current[key] -
                                (a.unit === "rad" ? 0.05 : 0.005),
                            ),
                          })
                        }
                      >
                        <Minus size={13} />
                      </button>
                      <input
                        type="number"
                        aria-label={`Control ${key}`}
                        step={a.unit === "rad" ? ".05" : ".005"}
                        min={a.min}
                        max={a.max}
                        value={targets[key] ?? 0}
                        disabled={!canAdjust}
                        onChange={(e) =>
                          updateTarget(key, e.target.valueAsNumber)
                        }
                      />
                      <button
                        aria-label={`Increase ${key}`}
                        disabled={!canAdjust}
                        onClick={() =>
                          void command({
                            ...targetRef.current,
                            [key]: Math.min(
                              a.max,
                              targetRef.current[key] +
                                (a.unit === "rad" ? 0.05 : 0.005),
                            ),
                          })
                        }
                      >
                        <Plus size={13} />
                      </button>
                      <output aria-label={`Feedback ${key}`}>
                        {session
                          ? session.feedback.positions[key]?.toFixed(4)
                          : "—"}{" "}
                        <small>{a.unit}</small>
                      </output>
                      {mode !== "live" && (
                        <input
                          className="manual-joint-slider"
                          type="range"
                          aria-label={`Control ${key} slider`}
                          min={a.min}
                          max={a.max}
                          step={a.unit === "rad" ? 0.01 : 0.001}
                          value={targets[key] ?? 0}
                          disabled={!canAdjust}
                          onChange={(e) =>
                            updateTarget(key, e.target.valueAsNumber)
                          }
                        />
                      )}
                    </div>
                  ),
                )}
              </div>
              <button
                className="primary"
                disabled={!canCommand}
                onClick={() => void command(targets)}
              >
                Send joint setpoints
              </button>
            </>
          )}
          {!manualAvailable && (
            <div className="command-joint-feedback">
              {Object.entries(robot.model.actuators.actuators).map(
                ([key, a]) => (
                  <div key={key}>
                    <span>{key}</span>
                    <output aria-label={`Feedback ${key}`}>
                      {session
                        ? session.feedback.positions[key]?.toFixed(4)
                        : "—"}{" "}
                      <small>{a.unit}</small>
                    </output>
                  </div>
                ),
              )}
            </div>
          )}
          <div className="control-feedback">
            <span>Connection: {session ? "connected" : "disconnected"}</span>
            <span>
              Stop requested: {session?.stop_requested ? "yes" : "no"}
            </span>
            <span>
              Stopped: {session?.stopped_verified ? "confirmed" : "unconfirmed"}
            </span>
            {session && (
              <small>
                Measured{" "}
                {new Date(session.feedback.measured_at).toLocaleTimeString()} ·{" "}
                {session.feedback.source}
              </small>
            )}
          </div>
          {session?.feedback.translated_command && (
            <details>
              <summary>Translated transport command</summary>
              <pre>
                {JSON.stringify(session.feedback.translated_command, null, 2)}
              </pre>
            </details>
          )}
        </div>
        <div className="control-preview scene-content">
          <Scene
            projectId={detail.project.id}
            model={robot.model}
            q={displayed.state.positions}
            robots={[
              {
                ...displayed,
                instance: {
                  ...displayed.instance,
                  base_pose: { x: 0, y: 0, z: 0, yaw: 0 },
                },
              },
            ]}
            objects={[]}
            path={[]}
            showGrid
            resetKey={0}
          />
          <span className="viewport-badge">
            {session
              ? mode === "test"
                ? "ISOLATED ADAPTER TEST"
                : mode === "live"
                  ? "MEASURED HARDWARE JOINTS"
                  : "MEASURED SIMULATOR JOINTS"
              : "CONNECT TO TEST THIS ADAPTER"}
          </span>
        </div>
      </div>
    </section>
  );
}

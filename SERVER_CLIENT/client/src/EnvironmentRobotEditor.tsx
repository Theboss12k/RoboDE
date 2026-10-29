import Feedback from "./ui/Feedback";
import NvidiaLogo from "./branding/NvidiaLogo";
import { useEffect, useRef, useState } from "react";
import { Check, RotateCcw, Square, X } from "lucide-react";
import { api, post } from "./api";
import { preferredAdapter, rememberAdapter } from "./adapterPreference";
import { useControlStream } from "./useControlStream";
import Scene, { type RobotBase } from "./Scene";
import type {
  AdapterBundle,
  CellRobot,
  ConnectionProfile,
  ControlSession,
  ProjectDetail,
  StandardCommand,
} from "./types";

type Draft = { base: RobotBase; positions: Record<string, number> };
export default function EnvironmentRobotEditor({
  detail,
  robot,
  draft,
  disabled,
  onDraft,
  onClose,
  onApplied,
  onBusy,
}: {
  detail: ProjectDetail;
  robot: CellRobot;
  draft: Draft;
  disabled: boolean;
  onDraft: (draft: Draft) => void;
  onClose: () => void;
  onApplied: () => Promise<void>;
  onBusy: (busy: boolean) => void;
}) {
  const original = useRef(structuredClone(robot));
  const latest = useRef(draft);
  latest.current = draft;
  const callbacks = useRef({ onDraft });
  callbacks.current = { onDraft };
  const [adapters, setAdapters] = useState<AdapterBundle[]>([]);
  const [adapter, setAdapter] = useState("");
  const [session, setSession] = useState<ControlSession | null>(null);
  const current = useRef<ControlSession | null>(null);
  const closed = useRef(new Set<string>());
  const [pending, setPending] = useState(false);
  const [working, setWorking] = useState(false);
  const inFlight = useRef(false);
  const polling = useRef(false);
  const [error, setError] = useState("");
  const [part, setPart] = useState(
    `actuator:${Object.keys(robot.model.actuators.actuators)[0]}`,
  );
  const [value, setValue] = useState(0);
  const [dragging, setDragging] = useState(false);
  const canIK =
    robot.model.planning_supported !== false &&
    ["analytic_yaw_two_link_v1", "serial_chain_dls_v1"].includes(
      robot.model.kinematics.solver,
    );
  const effectors = canIK
    ? Object.keys(robot.model.kinematics.end_effectors ?? {})
    : [];
  if (
    canIK &&
    !effectors.length &&
    robot.model.kinematics.solver === "analytic_yaw_two_link_v1"
  )
    effectors.push(robot.model.capabilities.end_effector);
  const [tool, setTool] = useState(effectors[0] ?? "");
  const [position, setPosition] = useState<[number, number, number]>([
    0.3, 0, 0.3,
  ]);
  const [orientation, setOrientation] = useState<
    [number, number, number] | null
  >(null);
  const body = useRef<HTMLDivElement>(null);
  const controlTabs = useRef<HTMLDivElement>(null);
  const [reset, setReset] = useState(0);
  const [retry, setRetry] = useState(0);
  const actuator = part.startsWith("actuator:") ? part.slice(9) : "";
  const spec = robot.model.actuators.actuators[actuator];
  const unavailable = pending || disabled;
  const setFeedback = (s: ControlSession) => {
    if (closed.current.has(s.id)) return;
    if (
      current.current?.id === s.id &&
      Date.parse(s.feedback.measured_at) <
        Date.parse(current.current.feedback.measured_at)
    )
      return;
    current.current = s;
    setSession(s);
    if (
      Object.entries(s.feedback.positions).some(
        ([key, value]) => latest.current.positions[key] !== value,
      )
    )
      callbacks.current.onDraft({
        ...latest.current,
        positions: s.feedback.positions,
      });
  };
  const motion = useControlStream<StandardCommand, ControlSession>({
    scope: session?.id ?? null,
    enabled: !!session && !unavailable,
    send: async (c) => {
      const s = await syncBase();
      return post<ControlSession>(`/controls/${s.id}/standard-command`, c);
    },
    onFeedback: setFeedback,
    onError: (e) => setError(e.message),
  });
  useEffect(() => {
    onBusy(working || motion.busy);
    return () => onBusy(false);
  }, [working, motion.busy, onBusy]);

  useEffect(() => {
    let disposed = false;
    Promise.all([
      api<AdapterBundle[]>(`/models/${robot.model.robot.id}/adapters`),
      api<ConnectionProfile[]>(
        `/projects/${detail.project.id}/robots/${robot.instance.instance.id}/connections`,
      ),
    ])
      .then(([all, profiles]) => {
        if (disposed) return;
        const approved = all.filter(
          (a) => a.reviewed_hash === a.hash && a.test_report?.passed,
        );
        setAdapters(approved);
        const configured = profiles.find((p) =>
          approved.some(
            (a) => a.id === p.adapter_id && a.hash === p.adapter_hash,
          ),
        );
        const saved = robot.instance.control_adapter?.adapter_id ?? preferredAdapter(
          detail.project.id,
          robot.instance.instance.id,
        );
        const validSaved =
          saved &&
          (["mock", "isaac_sim"].includes(saved) ||
            approved.some((a) => a.id === saved))
            ? saved
            : null;
        setAdapter(
          validSaved ??
            configured?.adapter_id ??
            approved.find((a) => a.kind === detail.adapter)?.id ??
            detail.adapter,
        );
      })
      .catch((e) => {
        if (!disposed) setError(String(e.message));
      });
    return () => {
      disposed = true;
    };
  }, [detail.project.id, robot.instance.instance.id, robot.model.robot.id]);

  useEffect(() => {
    if (!adapter) return;
    let disposed = false;
    let opened: ControlSession | null = null;
    setPending(true);
    inFlight.current = true;
    setError("");
    const timer = window.setTimeout(() => {
      post<ControlSession>(`/projects/${detail.project.id}/controls`, {
        robot_id: robot.instance.instance.id,
        adapter_id: adapter,
        mode: "test",
        preview: {
          positions: latest.current.positions,
          base_pose: latest.current.base,
        },
      })
        .then(async (s) => {
          opened = s;
          if (disposed) {
            await api(`/controls/${s.id}`, { method: "DELETE" });
            return;
          }
          setFeedback(s);
        })
        .catch((e) => {
          if (!disposed) setError(e.message);
        })
        .finally(() => {
          if (!disposed) {
            setPending(false);
            inFlight.current = false;
          }
        });
    }, 0);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      const needsClose = opened && !closed.current.has(opened.id);
      if (opened) closed.current.add(opened.id);
      if (opened && current.current?.id === opened.id) {
        current.current = null;
        setSession(null);
      }
      if (opened && needsClose)
        void api(`/controls/${opened.id}`, { method: "DELETE" }).catch(
          () => {},
        );
    };
  }, [adapter, retry, detail.project.id, robot.instance.instance.id]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (
        !current.current ||
        inFlight.current ||
        motion.active.current ||
        polling.current
      )
        return;
      const id = current.current.id;
      const revision = motion.revision.current;
      polling.current = true;
      api<ControlSession>(`/controls/${id}`)
        .then((s) => {
          if (
            inFlight.current ||
            motion.active.current ||
            motion.revision.current !== revision ||
            current.current?.id !== id
          )
            return;
          setFeedback(s);
        })
        .catch((e) => {
          if (
            inFlight.current ||
            motion.active.current ||
            motion.revision.current !== revision ||
            current.current?.id !== id
          )
            return;
          setError(e.message);
          current.current = null;
          setSession(null);
        })
        .finally(() => {
          polling.current = false;
        });
    }, 250);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (actuator && !motion.busy && !dragging)
      setValue(draft.positions[actuator] ?? 0);
  }, [actuator, draft.positions, motion.busy, dragging]);

  async function work(fn: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setWorking(true);
    setPending(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      inFlight.current = false;
      setWorking(false);
      setPending(false);
    }
  }
  async function syncBase() {
    const s = current.current;
    if (!s)
      throw new Error("Reconnect the simulated adapter to control this draft.");
    await api(`/controls/${s.id}/preview-base`, {
      method: "PUT",
      body: JSON.stringify(latest.current.base),
    });
    return s;
  }
  function command(c: StandardCommand) {
    setError("");
    motion.enqueue(c);
  }
  function jointTarget(next: number) {
    if (!spec || !Number.isFinite(next)) return;
    setValue(next);
    if (next >= spec.min && next <= spec.max)
      command({
        type: "SET_ACTUATOR",
        target: actuator,
        value: next,
        unit: spec.unit as "rad" | "m",
      });
  }
  function toolTarget(p: [number, number, number], r = orientation) {
    if (!p.every(Number.isFinite) || (r && !r.every(Number.isFinite))) return;
    command({
      type: "MOVE_END_EFFECTOR",
      target: tool,
      position: p,
      position_unit: "m",
      frame: robot.model.kinematics.world_frame ?? "world",
      ...(r ? { orientation_rpy: r, orientation_unit: "rad" as const } : {}),
    });
  }
  function readTool(target: string) {
    if (motion.active.current) return;
    void work(async () => {
      const s = await syncBase();
      const poses = await api<{
        positions: Record<string, [number, number, number]>;
      }>(`/controls/${s.id}/tool-poses`);
      if (poses.positions[target]) setPosition(poses.positions[target]);
    });
  }
  function selectPart(selected: string) {
    if (unavailable || motion.active.current) return;
    setPart(selected);
    requestAnimationFrame(() => {
      if (body.current && controlTabs.current)
        body.current.scrollTo({
          top: controlTabs.current.offsetTop,
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? "instant"
            : "smooth",
        });
    });
    if (selected.startsWith("effector:")) {
      const target = selected.slice(9);
      setTool(target);
      readTool(target);
    }
  }
  async function closeSession() {
    motion.cancel();
    const s = current.current;
    if (s) {
      await api(`/controls/${s.id}`, { method: "DELETE" });
      closed.current.add(s.id);
      current.current = null;
      setSession(null);
    }
  }
  const changed =
    JSON.stringify(draft.base) !==
      JSON.stringify(
        original.current.instance.base_pose ?? { x: 0, y: 0, z: 0, yaw: 0 },
      ) ||
    Object.entries(draft.positions).some(
      ([k, v]) =>
        Math.abs(
          v -
            original.current.instance.initial_configuration.actuator_positions[
              k
            ],
        ) > 1e-8,
    );
  return (
    <section
      className="config-card environment-robot-editor"
      aria-label="Robot virtual controls"
      aria-busy={pending || motion.busy}
      data-robot-id={robot.instance.instance.id}
    >
      <div className="section-toolbar">
        <div>
          <span className="eyebrow">ROBOT / DRAFT</span>
          <h3>{robot.instance.instance.name}</h3>
        </div>
        <button
          aria-label="Revert and close robot editor"
          disabled={pending}
          onClick={() =>
            void work(async () => {
              await closeSession();
              onClose();
            })
          }
        >
          <X size={16} />
        </button>
      </div>
      <p>Pick a joint or tool on the model to control it.</p>
      <div
        className="robot-inspector-preview"
        aria-label="Interactive robot model"
      >
        <Scene
          model={robot.model}
          q={draft.positions}
          objects={[]}
          path={[]}
          showGrid
          resetKey={reset}
          selectedPart={part}
          onSelectPart={selectPart}
        />
        <button
          className="preview-fit"
          aria-label="Reset robot preview camera"
          onClick={() => setReset(reset + 1)}
        >
          Reset view
        </button>
        <span className="preview-caption">
          {robot.model.kinematics.solver === "serial_chain_dls_v1"
            ? "Configured kinematic skeleton"
            : "Robot preview"}{" "}
          · click to select
        </span>
      </div>
      <div className="robot-editor-body" ref={body}>
        <label className="field">
          <span className="nvidia-tool-heading">
            Adapter
            {(adapter === "isaac_sim" ||
              adapters.some(
                (a) => a.id === adapter && a.kind === "isaac_sim",
              )) && <NvidiaLogo />}
          </span>
          <select
            aria-label="Robot preview adapter"
            value={adapter}
            disabled={pending || motion.busy}
            onChange={(e) => {
              motion.cancel();
              rememberAdapter(
                detail.project.id,
                robot.instance.instance.id,
                e.target.value,
              );
              setSession(null);
              setAdapter(e.target.value);
            }}
          >
            <option value="mock">Built-in simulator</option>
            <option value="isaac_sim">Isaac Sim · simulated test</option>
            {adapters.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.category}
              </option>
            ))}
          </select>
        </label>
        <div className="draft-connection">
          <span className={`status-dot ${session ? "online" : ""}`} />
          <span>
            {pending
              ? "Working…"
              : session
                ? "Connected · simulated feedback"
                : "Simulated adapter disconnected"}
          </span>
          <button
            className="stop-button"
            disabled={!session}
            onClick={() => {
              motion.cancel();
              if (current.current)
                void post<ControlSession>(
                  `/controls/${current.current.id}/stop`,
                )
                  .then(setFeedback)
                  .catch((e) => setError(e.message));
            }}
          >
            <Square size={11} /> Stop
          </button>
        </div>
        {session?.stop_requested && (
          <small role="status">
            {session.stopped_verified
              ? "Stopped · confirmed by simulated feedback"
              : "Stop requested · awaiting confirmation"}
          </small>
        )}
        {!session && !pending && (
          <button className="secondary" onClick={() => setRetry(retry + 1)}>
            Reconnect preview
          </button>
        )}
        <p className="preview-simulation-note">
          Controls update the simulation as you move them. Simulated transport ·
          no hardware connection. Apply commits to the selected simulator.
        </p>
        <div
          className="robot-control-tabs"
          ref={controlTabs}
          role="tablist"
          aria-label="Robot control mode"
        >
          <button
            role="tab"
            aria-selected={!!actuator}
            disabled={motion.busy}
            onClick={() =>
              selectPart(
                `actuator:${Object.keys(robot.model.actuators.actuators)[0]}`,
              )
            }
          >
            Individual joints
          </button>
          <button
            role="tab"
            aria-selected={!actuator}
            disabled={!effectors.length || !session || pending || motion.busy}
            onClick={() => selectPart(`effector:${tool}`)}
          >
            End effector
          </button>
        </div>
        {actuator && spec ? (
          <div className="robot-joint-control">
            <label className="field">
              Actuator
              <select
                aria-label="Preview actuator"
                value={actuator}
                disabled={unavailable || motion.busy}
                onChange={(e) => selectPart(`actuator:${e.target.value}`)}
              >
                {Object.keys(robot.model.actuators.actuators).map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </label>
            <div className="joint-value">
              <strong>{actuator.replaceAll("_", " ")}</strong>
              <span>
                {draft.positions[actuator]?.toFixed(4)} {spec.unit}
              </span>
            </div>
            <input
              aria-label="Joint target slider"
              type="range"
              min={spec.min}
              max={spec.max}
              step={spec.unit === "rad" ? 0.01 : 0.001}
              value={value}
              disabled={unavailable || !session}
              onPointerDown={() => setDragging(true)}
              onPointerUp={() => setDragging(false)}
              onPointerCancel={() => setDragging(false)}
              onBlur={() => setDragging(false)}
              onChange={(e) => jointTarget(e.target.valueAsNumber)}
            />
            <div className="joint-limits">
              <span>
                {spec.min} {spec.unit}
              </span>
              <span>
                {spec.max} {spec.unit}
              </span>
            </div>
            <div className="joint-command-row">
              <button
                className="secondary"
                aria-label="Decrease joint"
                disabled={unavailable || !session}
                onClick={() =>
                  jointTarget(
                    Math.max(
                      spec.min,
                      value - (spec.unit === "rad" ? 0.05 : 0.005),
                    ),
                  )
                }
              >
                −
              </button>
              <input
                aria-label="Preview joint target"
                type="number"
                min={spec.min}
                max={spec.max}
                step={spec.unit === "rad" ? 0.01 : 0.001}
                value={value}
                disabled={unavailable}
                onChange={(e) => jointTarget(e.target.valueAsNumber)}
              />
              <button
                className="secondary"
                aria-label="Increase joint"
                disabled={unavailable || !session}
                onClick={() =>
                  jointTarget(
                    Math.min(
                      spec.max,
                      value + (spec.unit === "rad" ? 0.05 : 0.005),
                    ),
                  )
                }
              >
                +
              </button>
              <button
                className="primary"
                disabled={unavailable || !session}
                onClick={() =>
                  command({
                    type: "SET_ACTUATOR",
                    target: actuator,
                    value,
                    unit: spec.unit as "rad" | "m",
                  })
                }
              >
                Move joint
              </button>
            </div>
          </div>
        ) : (
          <div className="robot-tool-control">
            <label className="field">
              End effector
              <select
                aria-label="Preview end effector"
                value={tool}
                disabled={unavailable || motion.busy}
                onChange={(e) => selectPart(`effector:${e.target.value}`)}
              >
                {effectors.map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </label>
            <p>World frame · metres · IK respects configured joint limits.</p>
            <div className="coordinate-inputs">
              {["X", "Y", "Z"].map((a, i) => (
                <label key={a}>
                  {a} · m
                  <input
                    aria-label={`Tool target ${a}`}
                    type="number"
                    step=".01"
                    value={Number(position[i].toFixed(5))}
                    disabled={unavailable}
                    onChange={(e) => {
                      const p = [...position] as [number, number, number];
                      if (!Number.isFinite(e.target.valueAsNumber)) return;
                      p[i] = e.target.valueAsNumber;
                      setPosition(p);
                      toolTarget(p);
                    }}
                  />
                </label>
              ))}
            </div>
            {robot.model.kinematics.solver === "serial_chain_dls_v1" && (
              <>
                <label className="field">
                  <span>
                    <input
                      type="checkbox"
                      checked={!!orientation}
                      disabled={unavailable}
                      onChange={(e) => {
                        const r: [number, number, number] | null = e.target
                          .checked
                          ? [0, 0, 0]
                          : null;
                        setOrientation(r);
                        toolTarget(position, r);
                      }}
                    />{" "}
                    Include orientation · rad
                  </span>
                </label>
                {orientation && (
                  <div className="coordinate-inputs">
                    {["Roll", "Pitch", "Yaw"].map((a, i) => (
                      <label key={a}>
                        {a}
                        <input
                          aria-label={`Tool ${a}`}
                          type="number"
                          step=".05"
                          value={orientation[i]}
                          disabled={unavailable}
                          onChange={(e) => {
                            const r = [...orientation] as [
                              number,
                              number,
                              number,
                            ];
                            if (!Number.isFinite(e.target.valueAsNumber))
                              return;
                            r[i] = e.target.valueAsNumber;
                            setOrientation(r);
                            toolTarget(position, r);
                          }}
                        />
                      </label>
                    ))}
                  </div>
                )}
              </>
            )}
            <div className="section-toolbar">
              <button
                className="secondary"
                disabled={unavailable || !session || motion.busy}
                onClick={() => readTool(tool)}
              >
                Read current tool pose
              </button>
              <button
                className="primary"
                disabled={unavailable || !session || !tool}
                onClick={() =>
                  command({
                    type: "MOVE_END_EFFECTOR",
                    target: tool,
                    position,
                    position_unit: "m",
                    frame: robot.model.kinematics.world_frame ?? "world",
                    ...(orientation
                      ? {
                          orientation_rpy: orientation,
                          orientation_unit: "rad" as const,
                        }
                      : {}),
                  })
                }
              >
                Move tool
              </button>
            </div>
          </div>
        )}
        <details className="draft-placement">
          <summary>Base position & rotation</summary>
          <div className="coordinate-inputs">
            {(["x", "y", "z", "yaw"] as const).map((a) => (
              <label key={a}>
                {a.toUpperCase()} · {a === "yaw" ? "rad" : "m"}
                <input
                  aria-label={`Draft base ${a}`}
                  type="number"
                  step=".01"
                  value={Number(draft.base[a].toFixed(4))}
                  disabled={unavailable}
                  onChange={(e) =>
                    onDraft({
                      ...draft,
                      base: { ...draft.base, [a]: Number(e.target.value) },
                    })
                  }
                />
              </label>
            ))}
          </div>
        </details>
        {session?.feedback.translated_command && (
          <details>
            <summary>Adapter feedback</summary>
            <pre>
              {JSON.stringify(session.feedback.translated_command, null, 2)}
            </pre>
          </details>
        )}
        <Feedback message={error} />
        {disabled && (
          <p>
            Save scene edits and stop active execution before applying a robot
            starting point.
          </p>
        )}
        {detail.adapter === "isaac_sim" && (
          <p>
            Apply reloads the managed native scene with this starting point.
            Other robot joint poses and object positions are retained; physics
            velocities reset.
          </p>
        )}
      </div>
      <div className="robot-draft-footer">
        <button
          className="secondary"
          disabled={pending}
          onClick={() =>
            void work(async () => {
              await closeSession();
              onClose();
            })
          }
        >
          <RotateCcw size={13} /> Revert
        </button>
        <button
          className="primary"
          disabled={unavailable || motion.busy || !changed}
          onClick={() =>
            void work(async () => {
              await closeSession();
              await api(
                `/projects/${detail.project.id}/robots/${robot.instance.instance.id}/starting-state`,
                {
                  method: "PUT",
                  body: JSON.stringify({
                    base_pose: latest.current.base,
                    positions: latest.current.positions,
                    expected_instance: original.current.instance,
                    expected_positions: original.current.state.positions,
                  }),
                },
              );
              await onApplied();
            })
          }
        >
          <Check size={13} /> Use as starting point
        </button>
      </div>
    </section>
  );
}

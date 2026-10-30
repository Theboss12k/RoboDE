import SceneRecordingPanel from "./SceneRecordingPanel";
import { randomId } from "./id";
import NvidiaLogo from "./branding/NvidiaLogo";
import EnvironmentRobotEditor from "./EnvironmentRobotEditor";
import type { RobotBase } from "./Scene";
import IsaacConnection from "./IsaacConnection";
import AdapterControls from "./AdapterControls";
import { useEffect, useState, useCallback, useRef } from "react";
import {
  Plus,
  RotateCcw,
  Save,
  Trash2,
  Plug,
  Unplug,
  Focus,
} from "lucide-react";
import type { ProjectDetail, WorldObject } from "./types";
import Scene from "./Scene";
import { useRobotWorkspace } from "./RobotWorkspace";
import IsaacRobotGuide from "./IsaacRobotGuide";
import ModelImport from "./ModelImport";
import RoomCaptureImport from "./RoomCaptureImport";
export default function EnvironmentWorkspace({
  detail,
  busy,
  onBackend,
  onRefresh,
  onReset,
  onDisconnect,
  onWorld,
  initialRobotId,
}: {
  initialRobotId?: string;
  detail: ProjectDetail;
  busy: boolean;
  onBackend: (backend: string, objects?: WorldObject[]) => void;
  onRefresh: () => void | Promise<void>;
  onReset: () => void;
  onDisconnect: () => void;
  onWorld: (objects: WorldObject[]) => void;
}) {
  const reachability = useRobotWorkspace(detail);
  const [recordingActive, setRecordingActive] = useState(false);
  const [editingRobot, setEditingRobot] = useState("");
  const [editorBusy, setEditorBusy] = useState(false);
  const [robotFocus, setRobotFocus] = useState<{
    id: string;
    request: string;
  }>();
  const [drafts, setDrafts] = useState<
    Record<string, { base: RobotBase; positions: Record<string, number> }>
  >({});
  const [transformMode, setTransformMode] = useState<"translate" | "rotate">(
    "translate",
  );
  const selectRobot = (id: string, focus = true) => {
    if (controlRobot || editorBusy || busy) return;
    const r = detail.robots.find((r) => r.instance.instance.id === id);
    if (!r) return;
    setEditingRobot(id);
    if (focus) setRobotFocus({ id, request: randomId() });
    setDrafts((prev) =>
      prev[id]
        ? prev
        : {
            ...prev,
            [id]: {
              base: {
                ...(r.instance.base_pose ?? { x: 0, y: 0, z: 0, yaw: 0 }),
              },
              positions: { ...r.state.positions },
            },
          },
    );
  };
  const clearDraft = () => {
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[editingRobot];
      return next;
    });
    setEditingRobot("");
  };
  const displayRobots = detail.robots.map((r) => {
    const d = drafts[r.instance.instance.id];
    return d
      ? {
          ...r,
          instance: { ...r.instance, base_pose: d.base },
          state: { ...r.state, positions: d.positions },
        }
      : r;
  });
  useEffect(() => {
    setEditingRobot("");
    setDrafts({});
  }, [detail.project.id]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        !editingRobot ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        (e.target as HTMLElement).closest(
          'input,textarea,select,[contenteditable="true"]',
        )
      )
        return;
      if (e.key.toLowerCase() === "g") setTransformMode("translate");
      if (e.key.toLowerCase() === "r") setTransformMode("rotate");
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [editingRobot]);
  const [controlRobot, setControlRobot] = useState("");
  useEffect(()=>{if(initialRobotId)selectRobot(initialRobotId)},[initialRobotId,detail.project.id]);
  const [controlsConnected, setControlsConnected] = useState(false);
  const refresh = useRef(onRefresh);
  refresh.current = onRefresh;
  useEffect(() => {
    if (!controlsConnected) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const update = async () => {
      try {
        await refresh.current();
      } catch {
        /* The control panel reports connection failures. Retry state reads. */
      }
      if (!disposed) timer = setTimeout(update, 150);
    };
    void update();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [controlsConnected, detail.project.id]);
  const nativeEditing =
    detail.adapter === "isaac_sim" && detail.worker?.scene_editing === true;
  const [objects, setObjects] = useState(detail.objects);
  const [modelStatus, setModelStatus] = useState<
    Record<string, "loading" | "loaded" | "error">
  >({});
  const reportModelStatus = useCallback(
    (id: string, status: "loading" | "loaded" | "error") =>
      setModelStatus((previous) => ({ ...previous, [id]: status })),
    [],
  );
  const [importBusy, setImportBusy] = useState(false);
  const [focus, setFocus] = useState<{ id: string; request: string }>();
  const savedObjects = JSON.stringify(detail.objects);
  const dirty = JSON.stringify(objects) !== savedObjects;
  const readOnly =
    busy ||
    importBusy ||
    !!controlRobot ||
    (detail.adapter === "isaac_sim" && !nativeEditing);
  const focusObject = (id: string) => setFocus({ id, request: randomId() });
  const addObject = (object: WorldObject) => {
    setObjects((previous) => [...previous, object]);
    focusObject(object.id);
  };
  const [grid, setGrid] = useState(true);
  const [reset, setReset] = useState(0);
  useEffect(() => {
    setObjects(JSON.parse(savedObjects));
    setFocus(undefined);
  }, [detail.project.id, savedObjects]);
  const robot = detail.robots[0];
  return (
    <div className="environment-workspace">
      <section className="environment-toolbar config-card">
        <div>
          <span className="eyebrow">ENVIRONMENT / SIMULATOR</span>
          <h2>Environment</h2>
        </div>
        <label className="field">
          <span className="nvidia-tool-heading">
            Simulation backend{detail.adapter === "isaac_sim" && <NvidiaLogo />}
          </span>
          <select
            aria-label="Simulation backend"
            disabled={busy || !!editingRobot || recordingActive}
            value={detail.adapter}
            onChange={(e) =>
              onBackend(e.target.value, dirty ? objects : undefined)
            }
          >
            <option value="mock">Built-in simulator</option>
            <option value="isaac_sim">NVIDIA Isaac Sim</option>
          </select>
        </label>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            const panel =
              document.querySelector<HTMLDetailsElement>(".isaac-connection");
            if (panel) {
              panel.open = true;
              panel.scrollIntoView({
                block: "start",
                behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                  .matches
                  ? "instant"
                  : "smooth",
              });
            }
          }}
        >
          <NvidiaLogo /> Isaac Sim setup
        </button>
        <button
          className="secondary"
          disabled={busy || !!editingRobot || recordingActive}
          onClick={() => onBackend(detail.adapter)}
        >
          <Plug size={13} /> Connect / read state
        </button>
        <button
          className="secondary"
          disabled={busy || !!editingRobot || recordingActive || !detail.environment_connected}
          onClick={onDisconnect}
        >
          <Unplug size={13} /> Disconnect
        </button>
        <button
          className="secondary"
          disabled={busy || !!editingRobot || recordingActive || !detail.environment_connected}
          onClick={onReset}
        >
          <RotateCcw size={13} /> Reset simulator
        </button>
      </section>
      {reachability.controls}
      <div className="environment-robot-toolbar placement-editor">
        <div className="scene-robot-picker">
          <span className="eyebrow">ROBOT CONTROLS</span><small>Select a robot to move its joints or tool.</small>
          {detail.robots.map((r) => (
            <button
              key={r.instance.instance.id}
              className={
                editingRobot === r.instance.instance.id ? "selected" : ""
              }
              disabled={busy || !!controlRobot || editorBusy}
              aria-label={`Control ${r.instance.instance.name}`}
              title="Open joint and end-effector controls"
              onClick={() => selectRobot(r.instance.instance.id)}
            >
              {r.instance.instance.name}
              {drafts[r.instance.instance.id] && <span className="draft-dot" />}
            </button>
          ))}
        </div>
        <div
          className="scene-transform-modes"
          role="group"
          aria-label="Robot transform mode"
        >
          <button
            aria-pressed={transformMode === "translate"}
            onClick={() => setTransformMode("translate")}
          >
            ↗ Move <kbd>G</kbd>
          </button>
          <button
            aria-pressed={transformMode === "rotate"}
            onClick={() => setTransformMode("rotate")}
          >
            ↻ Rotate <kbd>R</kbd>
          </button>
        </div>
      </div>
      <div
        className={`environment-layout ${reachability.visible ? "has-workspace-overlay" : ""}`}
      >
        <section
          className="environment-scene scene-content"
          data-scene-object-ids={objects.map((o) => o.id).join(",")}
          data-scene-saved={!dirty}
        >
          <Scene
            workspaces={reachability.overlay}
            workspaceFocus={reachability.focus}
            model={robot.model}
            q={robot.state.positions}
            robots={displayRobots}
            selectedRobot={editingRobot}
            robotFocus={robotFocus}
            onSelectRobot={selectRobot}
            transformMode={transformMode}
            editingDisabled={busy || !!controlRobot || editorBusy}
            onRobotTransform={(id, base) => {
              const r = detail.robots.find(
                (r) => r.instance.instance.id === id,
              );
              if (r)
                setDrafts((prev) => ({
                  ...prev,
                  [id]: {
                    positions: prev[id]?.positions ?? r.state.positions,
                    base,
                  },
                }));
            }}
            objects={objects}
            projectId={detail.project.id}
            focus={focus}
            onModelStatus={reportModelStatus}
            path={[]}
            showGrid={grid}
            resetKey={reset}
          />
          <div className="scene-interaction-hint">
            {editingRobot
              ? transformMode === "translate"
                ? "Drag robot on the ground · arrows move along an axis"
                : "Drag the rotation ring to change yaw"
              : "Click a robot to place or control it"}
            {Object.keys(drafts).length > 0 && (
              <span>Draft preview · apply or revert in robot controls</span>
            )}
          </div>
          <div className="viewport-controls">
            <button onClick={() => setGrid(!grid)}>
              Grid {grid ? "on" : "off"}
            </button>
            <button
              onClick={() => {
                setFocus(undefined);
                setRobotFocus(undefined);
                setReset(reset + 1);
              }}
            >
              Reset camera
            </button>
          </div>
          <span className="viewport-badge">
            {!detail.environment_connected
              ? "DISCONNECTED · LAST OBSERVED STATE"
              : detail.adapter === "mock"
                ? "BUILT-IN · IDEAL GRASPS"
                : "ISAAC SIM · CONNECTED WORKER"}{" "}
            · WORLD / m / Z UP
          </span>
          {dirty && (
            <span className="scene-draft-badge" role="status">
              Unsaved scene preview · Save scene to apply
            </span>
          )}
          <div className="scene-model-status" aria-label="Model loading status">
            {objects
              .filter((o) => o.mesh)
              .map((o) => (
                <span
                  key={o.id}
                  data-model-status={modelStatus[o.id] ?? "loading"}
                >
                  {o.name} ·{" "}
                  {modelStatus[o.id] === "loaded"
                    ? "model ready"
                    : modelStatus[o.id] === "error"
                      ? "model unavailable"
                      : "loading model…"}
                </span>
              ))}
          </div>
        </section>
        <div className="environment-editors">

          {editingRobot && drafts[editingRobot] && (
            <EnvironmentRobotEditor
              key={editingRobot}
              detail={detail}
              robot={
                detail.robots.find(
                  (r) => r.instance.instance.id === editingRobot,
                )!
              }
              draft={drafts[editingRobot]}
              disabled={busy || dirty || !!controlRobot}
              onBusy={setEditorBusy}
              onDraft={(draft) =>
                setDrafts((prev) => ({ ...prev, [editingRobot]: draft }))
              }
              onClose={clearDraft}
              onApplied={async () => {
                await onRefresh();
                clearDraft();
              }}
            />
          )}
          <SceneRecordingPanel key={detail.project.id} projectId={detail.project.id}
            connected={detail.adapter === 'isaac_sim' && detail.environment_connected}
            onActiveChange={setRecordingActive}/>
          <div
            className="environment-scene-editors"
            style={{ display: editingRobot ? "none" : undefined }}
          >
            <IsaacConnection
              disabled={busy || !!controlRobot}
              onChanged={onRefresh}
            />
            <IsaacRobotGuide />
            <details className="config-card room-import-card"><summary>Import room capture from mobile / USDZ</summary><RoomCaptureImport projectId={detail.project.id}/></details>
            {detail.adapter === "isaac_sim" && detail.environment_connected && (
              <section className="config-card native-controls">
                <div className="nvidia-tool-heading">
                  <NvidiaLogo />
                  <h3>Control robots in Isaac Sim</h3>
                </div>
                <p>
                  Joint targets go to the connected GPU scene; feedback comes
                  from its articulation. Close controls before editing objects
                  or running a plan.
                </p>
                {detail.robots.map((r) => (
                  <button
                    key={r.instance.instance.id}
                    disabled={busy || !!controlRobot}
                    onClick={() => setControlRobot(r.instance.instance.id)}
                  >
                    Control {r.instance.instance.name}
                  </button>
                ))}
                {controlRobot && (
                  <>
                    <button onClick={() => setControlRobot("")}>
                      Close native controls
                    </button>
                    <AdapterControls
                      key={controlRobot}
                      detail={detail}
                      robot={
                        detail.robots.find(
                          (r) => r.instance.instance.id === controlRobot,
                        )!
                      }
                      adapter="isaac_sim"
                      initialMode="environment"
                      onEnvironmentChanged={onRefresh}
                      onSessionChange={setControlsConnected}
                    />
                  </>
                )}
              </section>
            )}
            <section className="config-card world-editor">
              <div className="section-toolbar">
                <h3>Objects, regions & obstacles</h3>
                <button
                  className="secondary"
                  disabled={readOnly || !dirty}
                  onClick={() => onWorld(objects)}
                >
                  <Save size={13} /> Save scene
                </button>
              </div>
              <p>
                Additions and edits appear immediately in the preview. Save
                scene applies them to the simulator and keeps them after
                reopening.
              </p>
              {detail.adapter === "isaac_sim" && (
                <p className="inline-note">
                  Scene switches transfer robots, placements, joint positions
                  and objects automatically. Imported meshes keep their geometry
                  with neutral materials and bounding-box collisions in Isaac
                  Sim.
                </p>
              )}
              <ModelImport
                projectId={detail.project.id}
                disabled={
                  busy ||
                  readOnly ||
                  (detail.adapter === "isaac_sim" &&
                    !detail.worker?.asset_uploading)
                }
                onBusy={setImportBusy}
                onAdd={addObject}
              />
              <p className="scene-bounds-note">
                Scene dimensions define the bounding boxes used for collision
                and placement checks, including imported models.
              </p>
              {objects.map((o, i) => (
                <div className="object-form" key={o.id}>
                  <div>
                    <input
                      aria-label={`Object name ${o.id}`}
                      value={o.name}
                      disabled={readOnly}
                      onChange={(e) =>
                        setObjects(
                          objects.map((x, j) =>
                            j === i ? { ...x, name: e.target.value } : x,
                          ),
                        )
                      }
                    />
                    <span className="tiny-tag">{o.kind}</span>
                    <button
                      aria-label={`Focus ${o.name}`}
                      disabled={busy || !!editingRobot || recordingActive}
                      onClick={() => focusObject(o.id)}
                    >
                      <Focus size={13} />
                    </button>
                    <button
                      aria-label={`Remove ${o.name}`}
                      disabled={readOnly}
                      onClick={() =>
                        setObjects(objects.filter((x) => x.id !== o.id))
                      }
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  {o.mesh && (
                    <small className="imported-file-label">
                      {o.mesh.filename} · {o.mesh.up_axis} up
                    </small>
                  )}
                  <div className="coordinate-inputs">
                    {(["x", "y", "z"] as const).map((a) => (
                      <label key={a}>
                        {a.toUpperCase()}
                        <input
                          aria-label={`${o.name} ${a}`}
                          type="number"
                          step=".01"
                          value={o.position[a]}
                          disabled={readOnly}
                          onChange={(e) =>
                            setObjects(
                              objects.map((x, j) =>
                                j === i
                                  ? {
                                      ...x,
                                      position: {
                                        ...x.position,
                                        [a]: Number(e.target.value),
                                      },
                                    }
                                  : x,
                              ),
                            )
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <details>
                    <summary>Dimensions & mass</summary>
                    <div className="coordinate-inputs">
                      {(["x", "y", "z"] as const).map((a) => (
                        <label key={a}>
                          Size {a}
                          <input
                            aria-label={`${o.name} size ${a}`}
                            type="number"
                            step=".01"
                            min=".001"
                            value={o.size[a]}
                            disabled={readOnly}
                            onChange={(e) =>
                              setObjects(
                                objects.map((x, j) =>
                                  j === i
                                    ? {
                                        ...x,
                                        size: {
                                          ...x.size,
                                          [a]: Number(e.target.value),
                                        },
                                      }
                                    : x,
                                ),
                              )
                            }
                          />
                        </label>
                      ))}
                      <label>
                        kg
                        <input
                          aria-label={`${o.name} mass`}
                          type="number"
                          min="0"
                          step=".01"
                          value={o.mass_kg}
                          disabled={readOnly}
                          onChange={(e) =>
                            setObjects(
                              objects.map((x, j) =>
                                j === i
                                  ? { ...x, mass_kg: Number(e.target.value) }
                                  : x,
                              ),
                            )
                          }
                        />
                      </label>
                    </div>
                  </details>
                </div>
              ))}
              <div className="section-toolbar">
                {(["object", "region", "obstacle"] as const).map((kind) => (
                  <button
                    key={kind}
                    className="text-button"
                    disabled={readOnly}
                    onClick={() =>
                      addObject({
                        id: `${kind}_${randomId().replaceAll("-", "").slice(0, 12)}`,
                        name:
                          kind === "object"
                            ? "New object"
                            : kind === "region"
                              ? "New region"
                              : "Box obstacle",
                        kind,
                        position: { x: 0.2, y: 0.4, z: 0.15 },
                        size: { x: 0.1, y: 0.1, z: 0.1 },
                        mass_kg: kind === "object" ? 0.05 : 0,
                      })
                    }
                  >
                    <Plus size={12} /> {kind}
                  </button>
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

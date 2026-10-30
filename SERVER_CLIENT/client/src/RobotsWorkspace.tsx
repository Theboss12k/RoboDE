import PublishedBindings from "./PublishedBindings";
import { useEffect, useState } from "react";
import { Plus, Bot, Save } from "lucide-react";
import type { AdapterBundle, CellRobot, ProjectDetail } from "./types";
import { api } from "./api";
import Feedback from "./ui/Feedback";
import AddRobotForm from "./AddRobotForm";
import AdapterControls from "./AdapterControls";
import RobotAdapterPicker from "./RobotAdapterPicker";
import AdapterWizard from "./AdapterWizard";
export default function RobotsWorkspace({
  detail,
  busy,
  onRefresh,
  onError,
  onInitial,
  tutorialWizard,
  onOpenControls,
}: {
  onOpenControls: (id:string)=>void;
  detail: ProjectDetail;
  busy: boolean;
  onRefresh: () => void | Promise<void>;
  onError: (e: string) => void;
  onInitial: (id: string, q: Record<string, number>) => void;
  onModel: (
    id: string,
    a: CellRobot["model"]["actuators"]["actuators"],
    c: CellRobot["model"]["capabilities"],
  ) => void;
  tutorialWizard?: number;
}) {
  const [rid, setRid] = useState(detail.robots[0].instance.instance.id),
    [add, setAdd] = useState(false),
    [adapters, setAdapters] = useState<AdapterBundle[]>([]),
    [target, setTarget] = useState<"physical" | "virtual">("virtual"),
    [adapter, setAdapter] = useState("mock"),
    [saved, setSaved] = useState("mock"),
    [test, setTest] = useState(false),
    [active, setActive] = useState(false),
    [working, setWorking] = useState(false),
    [message, setMessage] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (
      pending &&
      detail.robots.some((r) => r.instance.instance.id === pending)
    ) {
      setRid(pending);
      setTest(true);
      setPending(null);
    }
  }, [detail.robots, pending]);
  const robot =
    detail.robots.find((r) => r.instance.instance.id === rid) ??
    detail.robots[0];
  const [positions, setPositions] = useState(
    robot.instance.initial_configuration.actuator_positions,
  );
  const binding = robot.instance.control_adapter;
  useEffect(() => {
    setTarget(binding?.category ?? "virtual");
    setAdapter(binding?.adapter_id ?? "mock");
    setSaved(binding?.adapter_id ?? "mock");
  }, [robot.instance.instance.id, binding?.adapter_id, binding?.category]);
  useEffect(
    () => setPositions(robot.instance.initial_configuration.actuator_positions),
    [
      robot.instance.instance.id,
      JSON.stringify(robot.instance.initial_configuration.actuator_positions),
    ],
  );
  useEffect(() => {
    let active = true;
    void api<AdapterBundle[]>(`/models/${robot.model.robot.id}/adapters`)
      .then((a) => {
        if (active) setAdapters(a);
      })
      .catch((e) => {
        if (active) onError(e.message);
      });
    return () => {
      active = false;
    };
  }, [robot.model.robot.id, robot.instance]);
  const locked = busy || working || active;
  const assign = async () => {
    setWorking(true);
    setMessage("");
    try {
      await api(
        `/projects/${detail.project.id}/robots/${robot.instance.instance.id}/adapter`,
        {
          method: "PUT",
          body: JSON.stringify({ adapter_id: adapter, category: target }),
        },
      );
      setSaved(adapter);
      setMessage(
        "Robot and adapter pairing saved to this project. Recompile affected plans.",
      );
      await onRefresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setWorking(false);
    }
  };
  return (
    <div className="robots-workspace">
      <div className="section-title">
        <span className="eyebrow">PROJECT / ROBOT INSTANCES</span>
        <h2>Robots in this project</h2>
        <p>
          Saved robots and control adapters live in Configuration → Robot
          library. Each project instance keeps its own pairing; task
          assignments remain explicit.
        </p>
      </div>
      <div className="robot-workspace-layout">
        <aside className="instance-list">
          <div className="section-toolbar">
            <h3>Project robots</h3>
            <button
              aria-label="Add robot instance"
              disabled={locked}
              onClick={() => setAdd(true)}
            >
              <Plus size={16} />
            </button>
          </div>
          {detail.robots.map((r) => (
            <button
              key={r.instance.instance.id}
              className={
                r.instance.instance.id === robot.instance.instance.id
                  ? "selected"
                  : ""
              }
              disabled={locked}
              onClick={() => {
                setRid(r.instance.instance.id);
                setTest(false);
                setMessage("");
              }}
            >
              <Bot size={18} />
              <span>
                {r.instance.instance.name}
                <small>
                  {r.model.robot.name} ·{" "}
                  {r.instance.control_adapter?.category ?? "virtual"}
                </small>
              </span>
            </button>
          ))}
          <p>Changing the selected robot does not reassign any tasks.</p>
        </aside>
        <section className="robot-editor config-card">
          <span className={`tiny-tag target-${target}`}>
            {target === "physical" ? "Physical target" : "Virtual target"}
          </span>
          <div className="section-toolbar"><h3>Robot</h3><button className="secondary" disabled={locked} onClick={()=>onOpenControls(robot.instance.instance.id)}>Open robot controls</button></div>
          <h2>{robot.model.robot.name}</h2>
          <p>
            Instance: {robot.instance.instance.name} ·{" "}
            {robot.instance.instance.id}
          </p>
          <small className="expert-only">
            Global definition: {robot.model.robot.id} ·{" "}
            {robot.model.robot.version}
          </small>
          <PublishedBindings detail={detail} robot={robot} disabled={locked} onRefresh={onRefresh}/><details className="expert-only" open={!robot.instance.control_adapter?.binding_id}><summary>Legacy simulator / adapter pairing</summary><h3>Compatible control adapter</h3>
          <RobotAdapterPicker
            target={target}
            onTarget={(t) => {
              setTarget(t);
              setAdapter(t === "virtual" ? "mock" : "");
              setTest(false);
            }}
            value={adapter}
            onChange={(a) => {
              setAdapter(a);
              setTest(false);
            }}
            adapters={adapters}
            disabled={locked}
          />
          <button
            className="primary"
            disabled={locked || !adapter || adapter === saved}
            onClick={() => void assign()}
          >
            <Save size={14} /> Save robot–adapter pairing
          </button>
          <Feedback message={message} kind="success" />
          <h3>3. Test this instance</h3>
          <p>
            Use the built-in simulator to test either target category. Physical
            testing uses injected simulated transport; it never contacts the
            device.
          </p>
          <button
            className="secondary"
            disabled={locked || adapter !== saved || !adapter}
            onClick={() => setTest(!test)}
          >
            {test ? "Close test window" : "Test selected adapter"}
          </button>
          {test && !robot.instance.control_adapter?.binding_id && (
            <AdapterControls
              key={robot.instance.instance.id + adapter}
              detail={detail}
              robot={robot}
              adapter={adapters.find((a) => a.id === adapter) ?? adapter}
              onEnvironmentChanged={onRefresh}
              onSessionChange={setActive}
            />
          )}
          </details><details className="instance-reference">
            <summary>Saved starting configuration</summary>
            <p>
              Joint positions and base placement can be previewed and saved in
              Environment by selecting this robot. Definition changes belong in
              Global configuration.
            </p>
            <p>
              Global model: {robot.model.robot.id}. Saving starting values does
              not move the robot. Apply them with Environment → Reset simulator.
            </p>
            <div className="configuration-grid">
              {Object.entries(robot.model.actuators.actuators).map(([k, a]) => (
                <label className="field" key={k}>
                  {k} · {a.unit}
                  <input
                    type="number"
                    aria-label={`Initial ${k}`}
                    min={a.min}
                    max={a.max}
                    step="any"
                    disabled={locked}
                    value={positions[k]}
                    onChange={(e) =>
                      setPositions({
                        ...positions,
                        [k]: Number(e.target.value),
                      })
                    }
                  />
                  <small>
                    Measured: {robot.state.positions[k].toFixed(4)} {a.unit}
                  </small>
                </label>
              ))}
            </div>
            <button
              disabled={locked}
              onClick={() => onInitial(robot.instance.instance.id, positions)}
            >
              Save configuration
            </button>
          </details>
        </section>
      </div>
      {tutorialWizard !== undefined && (
        <AdapterWizard
          detail={detail}
          robot={robot}
          globalModelId={robot.model.robot.id}
          previewStage={tutorialWizard}
          onClose={() => {}}
          onGenerated={() => {}}
        />
      )}
      {add && (
        <div className="modal-backdrop">
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Add project robot"
          >
            <AddRobotForm
              detail={detail}
              onCancel={() => setAdd(false)}
              onAdded={(id) => {
                setAdd(false);
                setPending(id ?? null);
                onRefresh();
                setMessage(
                  "Instance added. Test its saved adapter pairing below.",
                );
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

import Feedback from "./ui/Feedback";
import { useEffect, useState } from "react";
import { api, post } from "./api";
import RobotAdapterPicker from "./RobotAdapterPicker";
import type { AdapterBundle, Model, ProjectDetail } from "./types";

export default function AddRobotForm({
  detail,
  onAdded,
  onCancel,
}: {
  detail: ProjectDetail;
  onAdded: (id?:string) => void;
  onCancel: () => void;
}) {
  const [models, setModels] = useState<Model[]>([]),
    [modelId, setModelId] = useState("");
  const [adapters,setAdapters]=useState<AdapterBundle[]>([]);
  const [target,setTarget]=useState<"physical"|"virtual">("virtual"),[adapter,setAdapter]=useState("mock"),[step,setStep]=useState(0);
  useEffect(()=>{setAdapter("mock");setTarget("virtual");if(modelId)void api<AdapterBundle[]>(`/models/${modelId}/adapters`).then(setAdapters).catch(e=>setError(e.message));},[modelId]);
  const [name, setName] = useState(""),
    [id, setId] = useState(() => {
      let n = 1;
      const ids = new Set(detail.robots.map((r) => r.instance.instance.id));
      while (ids.has(`arm_${String(n).padStart(2, "0")}`)) n++;
      return `arm_${String(n).padStart(2, "0")}`;
    });
  const [q, setQ] = useState<Record<string, number>>({});
  const [base, setBase] = useState({
    x: 0,
    y: detail.robots.length * 1.3,
    z: 0,
    yaw: 0,
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void api<Model[]>("/registry")
      .then((m) => {
        if (!active) return;
        setModels(m);
        setModelId(m[0]?.robot.id ?? "");
        setQ(m[0]?.initial_configuration?.actuator_positions ?? {});
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  const model = models.find((m) => m.robot.id === modelId);
  return (
    <form
      className="robot-add-form"
      onSubmit={(e) => {
        e.preventDefault();
        if(step===0){setStep(1);return;}
        setBusy(true);
        setError("");
        void post(`/projects/${detail.project.id}/robots`, {
          id,
          name: name.trim() || id,
          model_id: modelId,
          initial_positions: q,
          base_pose: base,
          adapter_id: adapter,
          category: target,
        })
          .then(()=>onAdded(id))
          .catch((e) => setError(e.message))
          .finally(() => setBusy(false));
      }}
    >
      <h2>Add project robot</h2>
      <ol className="wizard-stages"><li className={step===0?"active":"done"}><span>1</span>Select global robot</li><li className={step===1?"active":""}><span>2</span>Select adapter</li><li><span>3</span>Test instance</li></ol>
      <p>
        Select a registered model, name this instance and set its starting
        configuration. New definitions and adapters are created in Global configuration.
      </p>
      <label className="field">
        Registered model
        <select
          aria-label="New robot model"
          value={modelId}
          disabled={busy}
          onChange={(e) => {
            setModelId(e.target.value);
            setQ(
              models.find((m) => m.robot.id === e.target.value)
                ?.initial_configuration?.actuator_positions ?? {},
            );
          }}
        >
          {models.map((m) => (
            <option key={m.robot.id} value={m.robot.id}>
              {m.robot.name} · {m.robot.id}
            </option>
          ))}
        </select>
      </label>
      {model?.planning_supported === false && (
        <p className="inline-note">
          Configuration and joint simulation are available. Motion planning
          needs a verified kinematics solver. The scene displays a model marker.
        </p>
      )}
      <div className="configuration-grid">
        <label className="field">
          Instance ID
          <input
            aria-label="New robot ID"
            pattern="[a-z][a-z0-9_]{0,39}"
            maxLength={40}
            required
            value={id}
            disabled={busy}
            onChange={(e) => setId(e.target.value)}
          />
        </label>
        <label className="field">
          Instance name
          <input
            aria-label="New robot name"
            value={name}
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
      </div>
      {step===1&&<RobotAdapterPicker target={target} onTarget={t=>{setTarget(t);setAdapter(t==="virtual"?"mock":"")}} value={adapter} onChange={setAdapter} adapters={adapters} disabled={busy}/>}
      <details><summary>Optional · initial joints and placement</summary>
      <h3>Initial joints</h3>
      <div className="configuration-grid">
        {Object.entries(model?.actuators.actuators ?? {}).map(([key, a]) => (
          <label className="field" key={key}>
            {key} · {a.unit}
            <input
              aria-label={`New robot joint ${key}`}
              type="number"
              min={a.min}
              max={a.max}
              step="any"
              value={q[key] ?? 0}
              disabled={busy}
              required
              onChange={(e) => setQ({ ...q, [key]: Number(e.target.value) })}
            />
            <small>
              {a.min} … {a.max} {a.unit}
            </small>
          </label>
        ))}
      </div>
      <h3>Base placement</h3>
      <div className="coordinate-inputs">
        {(["x", "y", "z", "yaw"] as const).map((a) => (
          <label key={a}>
            {a} · {a === "yaw" ? "rad" : "m"}
            <input
              aria-label={`New robot base ${a}`}
              type="number"
              step="any"
              min={a === "z" ? 0 : undefined}
              value={base[a]}
              disabled={busy}
              onChange={(e) =>
                setBase({ ...base, [a]: Number(e.target.value) })
              }
            />
          </label>
        ))}
      </div>
      </details>
      <Feedback message={error} />
      <div className="section-toolbar">
        <button type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button className="primary" type="submit" disabled={busy || !model || (step===1&&!adapter)}>
          {busy ? "Adding…" : step===0?"Continue to adapter":"Add instance & test"}
        </button>
      </div>
    </form>
  );
}

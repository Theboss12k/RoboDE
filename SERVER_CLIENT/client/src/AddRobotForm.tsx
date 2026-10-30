import Feedback from "./ui/Feedback";
import { useEffect, useState } from "react";
import { api, post } from "./api";
import RobotAdapterPicker from "./RobotAdapterPicker";
import type { AdapterBundle, Model, ProjectDetail } from "./types";

type Pairing={id:string;published:boolean;validation_status?:string;definition:{model_id:string;driver_id:string}};

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
  const [pairings,setPairings]=useState<Pairing[]>([]),[drivers,setDrivers]=useState<{id:string;definition:{name:string;category:"virtual"|"physical"}}[]>([]),[pairing,setPairing]=useState("");
  useEffect(()=>{setAdapter("mock");setTarget("virtual");setPairing("");if(modelId)void api<AdapterBundle[]>(`/models/${modelId}/adapters`).then(setAdapters).catch(e=>setError(e.message));},[modelId]);
  useEffect(()=>{void Promise.all([api<Pairing[]>("/library/robot-bindings"),api<typeof drivers>("/library/drivers")]).then(([b,d])=>{setPairings(b);setDrivers(d)}).catch(e=>setError(e.message))},[]);
  // Saved robot configurations from Robot library are the primary choice; legacy adapters stay available in Expert mode.
  const compatible=pairings.filter(b=>b.published&&b.validation_status!=="stale"&&b.definition.model_id===modelId);
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
        const chosen=pairings.find(b=>b.id===pairing);
        const category=chosen?drivers.find(d=>d.id===chosen.definition.driver_id)?.definition.category??"virtual":target;
        void post(`/projects/${detail.project.id}/robots`, {
          id,
          name: name.trim() || id,
          model_id: modelId,
          initial_positions: q,
          base_pose: base,
          adapter_id: chosen?(category==="virtual"?"mock":adapter):adapter,
          category,
        })
          .then(async()=>{if(chosen)await api(`/projects/${detail.project.id}/robots/${id}/binding`,{method:"PUT",body:JSON.stringify({binding_id:chosen.id})});onAdded(id)})
          .catch((e) => setError(e.message))
          .finally(() => setBusy(false));
      }}
    >
      <h2>Add project robot</h2>
      <ol className="wizard-stages"><li className={step===0?"active":"done"}><span>1</span>Select robot</li><li className={step===1?"active":""}><span>2</span>Select control adapter</li><li><span>3</span>Add instance & test</li></ol>
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
      {step===1&&<><label className="field">Control adapter<select aria-label="Saved robot configuration" value={pairing} disabled={busy} onChange={e=>setPairing(e.target.value)}>
        <option value="">{compatible.length?"Choose a saved configuration":"No saved configuration for this robot"}</option>
        {compatible.map(b=>{const d=drivers.find(x=>x.id===b.definition.driver_id);return <option key={b.id} value={b.id}>{d?.definition.name??"Adapter"} · {d?.definition.category==="physical"?"Physical":"Virtual"}</option>})}</select></label>
        {!compatible.length&&<small>Save this robot with a control adapter in Configuration → Robot library, or use the built-in simulator below.</small>}
        <details className="expert-only" open={!compatible.length}><summary>Legacy simulator / adapter pairing</summary><RobotAdapterPicker target={target} onTarget={t=>{setTarget(t);setAdapter(t==="virtual"?"mock":"");setPairing("")}} value={adapter} onChange={a=>{setAdapter(a);setPairing("")}} adapters={adapters} disabled={busy}/></details>
        {!compatible.length&&<p className="simple-only inline-note">Without a saved configuration, the instance uses the built-in kinematic simulator.</p>}</>}
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
        <button className="primary" type="submit" disabled={busy || !model || (step===1&&!adapter&&!pairing)}>
          {busy ? "Adding…" : step===0?"Continue to adapter":"Add instance & test"}
        </button>
      </div>
    </form>
  );
}

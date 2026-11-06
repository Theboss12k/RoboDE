import { useEffect, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import { Sparkles } from "lucide-react";
import { api, post, ApiError } from "./api";
import type { LLMConfiguration, Model, RoleSettings } from "./types";
import type { Driver } from "./ControlAdapters";
import GeneratedFunctions, { type GeneratedDraft, type Issue } from "./GeneratedFunctions";
import MotionWorkerSetup from "./MotionWorkerSetup";
import { functionFor } from "./RobotSetup";
import { Robot } from "./Scene";
import Feedback from "./ui/Feedback";
import "./ui/robotics.css";
import "./ui/auto-setup.css";

type Source = { source: "urdf" | "documentation" | "derived" | "default" | "ai"; quote?: string; as_written?: string; note?: string };
type Values = { min: number | null; max: number | null; velocity: number | null; acceleration: number | null; initial: number | null };
type Review = { id: string; name: string; manufacturer: string; description: string; tool_link: string | null; joints: Record<string, Values>;
  payload_kg: number | null; gripper_actuator: string | null; gripper_closed: number | null; gripper_open: number | null };
type Mobility = Record<string, unknown> & { classification: "STATIONARY" | "MOVING" | "BOTH"; left_wheel?: string; right_wheel?: string; map_frame?: string };
type Prefill = { review: Review; mobility: Mobility | null; provenance: Record<string, Source>; issues: Issue[]; notes: string[]; llm: { model?: string | null } | null };
type Row = { joint_id: string; alias: string; role: "independent" | "passive" | "coupled"; function_id: string | null; scale: number; offset: number; multiplier: number; coupled_to?: string };
type Mapping = { description: string; joints: Row[]; issues: Issue[]; notes: string[] };
type Generated = { status: "complete"; driver: Driver } | { status: "needs_information"; draft: GeneratedDraft; issues: Issue[] } | { status: "simulator" };
type Stage = { status: string; message: string };
type Job = { id: string; status: "running" | "done" | "failed"; error: string | null; stages: Record<keyof typeof STAGES, Stage>;
  result: { prefill: Prefill; adapter: Generated; mapping: Mapping | null } | null };
type Draft = { id: string; parsed: { name: string; links: string[]; joints: { name: string; type: string }[] } };
type Binding = { id: string; hash: string; published: boolean;
  test_evidence: Record<string, { passed: boolean; tested_joints?: string[]; positions?: Record<string, number>; samples?: { positions: Record<string, number> }[] }> };
type Check = "works" | "wrong";

const FIELDS = ["min", "max", "velocity", "acceleration", "initial"] as const;
const STAGES = { prefill: "Read URDF and documentation", adapter: "Generate control adapter", mapping: "Map joints to functions" };
const LABELS: Record<Source["source"], string> = { urdf: "URDF", documentation: "Documented", derived: "From URDF geometry", default: "Default · review", ai: "AI wording" };
const MOBILE_FIELDS = [["wheel_radius_m", "Wheel radius (m)"], ["track_width_m", "Track width (m)"], ["max_linear_m_s", "Max speed (m/s)"], ["max_angular_rad_s", "Max turn rate (rad/s)"]] as const;
const num = (text: string) => (text.trim() === "" ? null : Number(text));
const fmt = (v: number | null | undefined) => (v === null || v === undefined ? "–" : Number(v.toPrecision(6)).toString());

/** Where a prefilled value came from; the quote or note shows on hover. */
function Badge({ p }: { p?: Source }) {
  if (!p) return null;
  const title = [p.as_written && `Written as ${p.as_written}`, p.quote && `“${p.quote}”`, p.note].filter(Boolean).join("\n");
  return <span className={`source-badge ${p.source}`} title={title || undefined}>{LABELS[p.source]}</span>;
}

/** Robot setup from a URDF and vendor documentation: the AI proposes every value, the user reviews, tries each
 *  generated function in simulation, then saves. Nothing is saved or tested before the user accepts. */
export default function AutoSetup({ disabled, onDone, onCancel, onBusyChange }: { disabled: boolean; onDone: () => void; onCancel: () => void; onBusyChange?: (busy: boolean) => void }) {
  const [phase, setPhase] = useState<"upload" | "working" | "review" | "try">("upload");
  const [file, setFile] = useState<File | null>(null), [docs, setDocs] = useState(""), [category, setCategory] = useState<"virtual" | "physical">("virtual");
  const [providers, setProviders] = useState<LLMConfiguration>({ default_id: null, adapters: [] }), [provider, setProvider] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null), [job, setJob] = useState<Job | null>(null);
  const [review, setReview] = useState<Review | null>(null), [mobility, setMobility] = useState<Mobility | null>(null), [rows, setRows] = useState<Row[]>([]);
  const [generated, setGenerated] = useState<Generated | null>(null), [errors, setErrors] = useState<Record<string, string>>({});
  const [driver, setDriver] = useState<Driver | null>(null), [model, setModel] = useState<Model | null>(null), [binding, setBinding] = useState<Binding | null>(null);
  const [savedModel, setSavedModel] = useState<Model | null>(null);
  const [q, setQ] = useState<Record<string, number>>({}), [checks, setChecks] = useState<Record<string, Check>>({}), [results, setResults] = useState<Record<string, string>>({});
  const [setupDraft, setSetupDraft] = useState<{ id: string; version: number; data: Record<string, unknown> } | null>(null);
  const [move, setMove] = useState({ target: "tool", x: .3, y: 0, z: .3 }), [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const locked = disabled || !!busy;
  useEffect(() => { onBusyChange?.(!!busy); }, [busy, onBusyChange]);
  useEffect(() => {
    void api<LLMConfiguration>("/llm/adapters").then(setProviders).catch(e => setError(e.message));
    void api<RoleSettings>("/llm/roles").then(r => setProvider(r.setup_adapter_id || r.binding_adapter_id || "")).catch(() => {});
  }, []);
  const work = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  };
  const result = job?.result, prefill = result?.prefill;
  const source = (field: string) => prefill?.provenance[field];

  const configure = () => work("Configuring…", async () => {
    if (!file) throw Error("Choose the robot's URDF or ZIP file");
    if (category === "physical" && !docs.trim()) throw Error("A physical robot needs its vendor documentation to generate the control adapter");
    const d = await api<Draft>(`/registry/urdf/drafts?filename=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
    setDraft(d);
    let j = await post<Job>("/library/auto-setup", { draft_id: d.id, documentation: docs, category, adapter_id: provider || null });
    setJob(j); setPhase("working");
    while (j.status === "running") { await new Promise(r => setTimeout(r, 1000)); j = await api<Job>(`/library/auto-setup/${j.id}`); setJob(j); }
    if (j.status === "failed" || !j.result) throw Error(j.error || "Setup failed");
    setReview(j.result.prefill.review); setMobility(j.result.prefill.mobility); setGenerated(j.result.adapter);
    setRows(j.result.mapping?.joints ?? []); setDriver(j.result.adapter.status === "complete" ? j.result.adapter.driver : null); setPhase("review");
  });
  const loadManual = (f: File) => work("Reading documentation…", async () => {
    const r = await api<{ text: string }>(`/library/manuals?filename=${encodeURIComponent(f.name)}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: f });
    setDocs(r.text);
  });
  const setJoint = (joint: string, field: keyof Values, text: string) => {
    if (!review) return;
    setReview({ ...review, joints: { ...review.joints, [joint]: { ...review.joints[joint], [field]: num(text) } } });
    setErrors(e => { const n = { ...e }; delete n[`joints.${joint}.${field}`]; return n; });
  };
  const remap = () => work("Proposing the mapping…", async () => {
    if (!job) return;
    const m = await post<Mapping>(`/library/auto-setup/${job.id}/mapping`, { adapter_id: provider || null });
    setRows(m.joints); setJob({ ...job, result: job.result && { ...job.result, mapping: m } });
    setNotice(m.issues.length ? `${m.issues.length} mapping issue${m.issues.length > 1 ? "s" : ""} remain; see the list above.` : "Every joint is mapped. Check each one.");
  });
  // Saves run one at a time: each needs the version the previous save returned.
  const saving = useRef(Promise.resolve()), latest = useRef(setupDraft);
  useEffect(() => { latest.current = setupDraft; }, [setupDraft]);
  const persist = (data: Record<string, unknown>) => {
    saving.current = saving.current.then(async () => {
      const d = latest.current;
      if (!d) return;
      const saved = await api<{ id: string; version: number; data: Record<string, unknown> }>(`/library/setup-drafts/${d.id}`, { method: "PUT", body: JSON.stringify({ version: d.version, stage: 3, data: { ...d.data, ...data } }) });
      latest.current = saved; setSetupDraft(saved);
    }).catch(e => setError((e as Error).message));
    return saving.current;
  };

  /** Accepting saves the reviewed model, reviews and tests the adapter, and saves an unpublished mapping. */
  const accept = () => work("Building the robot…", async () => {
    if (!draft || !review) return;
    setErrors({});
    try { await post(`/registry/urdf/drafts/${draft.id}/validate`, review); }
    catch (e) {
      if (e instanceof ApiError && e.errors.length) {
        setErrors(Object.fromEntries(e.errors.map(x => [x.field, x.message])));
        throw Error(`${e.errors.length} value${e.errors.length > 1 ? "s need" : " needs"} attention; each is marked below.`);
      }
      throw e;
    }
    // Each finished step is kept, so retrying after a failure continues instead of saving the robot twice.
    const saved = savedModel ?? await post<Model>(`/registry/urdf/drafts/${draft.id}/commit`, { ...review, reviewed: true });
    setSavedModel(saved);
    let d = driver, mapping = rows;
    if (!d && generated?.status === "needs_information") throw Error("Complete the control adapter table first");
    if (!d) {
      d = await post<Driver>(`/library/drivers/simulator/${saved.robot.id}`);
      const ids = new Set(d.definition.functions.map(f => f.id));
      mapping = Object.keys(review.joints).map(j => ({ joint_id: j, alias: j.replaceAll("_", " "), role: "independent", function_id: ids.has(functionFor(j)) ? functionFor(j) : null, scale: 1, offset: 0, multiplier: 1 }));
      setDriver(d); setRows(mapping);
    } else if (!mapping.length) {
      mapping = (await post<Mapping>("/library/robot-bindings/suggest", { model_id: saved.robot.id, driver_id: d.id, adapter_id: provider || null })).joints;
      setRows(mapping);
    }
    if (d.reviewed_hash !== d.hash) d = await post<Driver>(`/library/drivers/${d.id}/review`, { expected_hash: d.hash });
    if (!d.test_report?.passed) d = await post<Driver>(`/library/drivers/${d.id}/test`);
    if (!d.test_report?.passed) throw Error("The control adapter failed its simulated tests");
    const tools = mobility?.classification === "MOVING" ? {} : { tool: { link: review.tool_link, xyz: [0, 0, 0], rpy: [0, 0, 0] } };
    const motion = mobility ?? { classification: "STATIONARY", priority: "arm_first" };
    const b = await post<Binding>("/library/robot-bindings", { physical_description: review.description, model_id: saved.robot.id, driver_id: d.id, joints: mapping, end_effectors: tools, mobility: motion });
    const full = await api<Model>(`/library/models/${saved.robot.id}`);
    const start = full.initial_configuration?.actuator_positions ?? {};
    setModel(full); setDriver(d); setRows(mapping); setBinding(b); setQ(start); marks.current = {}; setChecks({}); setResults({});
    setMove(m => ({ ...m, target: mobility?.classification === "MOVING" ? "base" : "tool" }));
    // The same draft opens in the step-by-step wizard at its Test step, for anything this page doesn't cover.
    const data = { flow: 5, category, description: review.description, driver_id: d.id, model_id: saved.robot.id, mapping, binding_id: b.id, name: d.definition.name,
      version: d.definition.sdk_version, manual: docs, source: d.source_code, motion, tools, bounds: "", reviewed: false, q: start, grasp: false, contacts: {}, function_checks: {} };
    setSetupDraft(await post<{ id: string; version: number; data: Record<string, unknown> }>("/library/setup-drafts", { stage: 3, data }));
    setPhase("try"); setNotice("Robot built. Try each function below and mark whether it moved as expected.");
  });

  const functionOf = (row: Row) => driver?.definition.functions.find(f => f.id === row.function_id);
  const triesFor = (row: Row): [string, number][] => {
    const spec = model!.actuators.actuators[row.joint_id];
    return functionOf(row)?.mode === "velocity" ? [["Spin back", -spec.velocity / 2], ["Spin forward", spec.velocity / 2]] : [["Min", spec.min], ["Max", spec.max], ["Middle", (spec.min + spec.max) / 2]];
  };
  /** One simulated call through the generated adapter; returns the new joint positions. */
  const send = async (row: Row, value: number, label: string, positions: Record<string, number>) => {
    if (!binding) return positions;
    try {
      const next = await post<Binding>(`/library/robot-bindings/${binding.id}/test-actuators`, { joint_id: row.joint_id, value, positions });
      setBinding(next); const p = next.test_evidence.actuators?.positions ?? positions; setQ(p);
      const f = functionOf(row);
      const velocity = f?.mode === "velocity", unit = model?.actuators.actuators[row.joint_id]?.unit ?? "";
      // A wheel's position keeps changing, so report how far this command turned it.
      const feedback = velocity ? `turned ${fmt(p[row.joint_id] - (positions[row.joint_id] ?? 0))} ${unit} in 0.2 s` : `feedback ${fmt(p[row.joint_id])} ${unit}`;
      setResults(r => ({ ...r, [row.joint_id]: `${label}: sent ${f?.vendor_method ?? f?.id}(${fmt(velocity ? value * row.scale : value * row.scale + row.offset)} ${f?.unit}); ${feedback}` }));
      return p;
    } catch (e) { setResults(r => ({ ...r, [row.joint_id]: `${label} failed: ${(e as Error).message}` })); return positions; }
  };
  const tryValue = (row: Row, value: number, label: string) => work(`Trying ${row.alias || row.joint_id}…`, async () => { await send(row, value, label, q); });
  const tryAll = () => work("Trying every function…", async () => {
    let positions = q;
    for (const row of rows.filter(r => r.role === "independent" && r.function_id))
      for (const [label, value] of triesFor(row)) { positions = await send(row, value, label, positions); await new Promise(r => setTimeout(r, 300)); }
    setNotice("Every function was tried. Mark each one Works or Wrong from what you saw.");
  });
  // Marks build on the latest set, even when several land before the next render.
  const marks = useRef<Record<string, Check>>({});
  const mark = (joint: string, value: Check) => { marks.current = { ...marks.current, [joint]: value }; setChecks(marks.current); void persist({ function_checks: marks.current }); };
  const testMove = () => work("Testing MOVE…", async () => {
    if (!binding || !model) return;
    const base = move.target === "base";
    const next = await post<Binding>(`/library/robot-bindings/${binding.id}/test-move`, { target: move.target, position: base ? [move.x, move.y] : [move.x, move.y, move.z],
      frame: base ? String(mobility?.map_frame ?? "map") : model.kinematics.world_frame ?? "world" });
    setBinding(next); const samples = next.test_evidence.move?.samples; if (samples?.length) setQ(samples[samples.length - 1].positions);
    setNotice("MOVE compiled and checked in the robotics worker.");
  });
  const save = () => work("Saving…", async () => {
    if (!binding) return;
    await post(`/library/robot-bindings/${binding.id}/review`, { expected_hash: binding.hash });
    await post(`/library/robot-bindings/${binding.id}/publish`);
    onDone();
  });

  if (phase === "upload" || phase === "working") return <section className="config-card auto-setup" aria-label="Set up a robot with AI">
    <h3>Set up a robot with AI</h3>
    <p>Give RoboDE the robot's URDF and its vendor documentation. It fills in every setting, writes the control adapter and maps each joint to it. You review the result, try each function in simulation, then save.</p>
    {phase === "upload" ? <>
      <label className="field">URDF or ZIP with meshes<input type="file" accept=".urdf,.zip" aria-label="Robot URDF file" disabled={locked} onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
      <label className="field">Vendor documentation · SDK manual, datasheet or API reference
        <textarea aria-label="Vendor documentation" value={docs} disabled={locked} maxLength={60000} rows={6} onChange={e => setDocs(e.target.value)} placeholder="Paste the documentation, or upload a searchable PDF, Markdown or text file below" /></label>
      <label className="file-button">Upload documentation<input type="file" accept=".pdf,.txt,.md,.json,.yaml,.yml" disabled={locked} onChange={e => { const f = e.target.files?.[0]; if (f) void loadManual(f); }} /></label>
      <small>{docs.length.toLocaleString()} / 60,000 characters. Without documentation, a simulator adapter is made from the robot's joints.</small>
      <div className="target-choice" role="group" aria-label="Execution target">{(["virtual", "physical"] as const).map(c => <button key={c} aria-pressed={category === c} disabled={locked} onClick={() => setCategory(c)}>{c === "virtual" ? "Virtual · simulator" : "Physical · robot hardware"}</button>)}</div>
      <label className="field">AI model<select aria-label="Setup AI model" value={provider} disabled={locked} onChange={e => setProvider(e.target.value)}>
        <option value="">{providers.default_id ? "Workspace default" : "Choose an AI model"}</option>{providers.adapters.map(p => <option key={p.id} value={p.id}>{p.name} · {p.model}</option>)}</select></label>
      <div className="section-toolbar"><button className="primary" disabled={locked || !file} onClick={() => void configure()}><Sparkles size={14} /> {busy || "Configure with AI"}</button><button disabled={locked} onClick={onCancel}>Cancel</button></div>
    </> : <ol className="stage-list" aria-label="Setup progress">{job && (Object.keys(STAGES) as (keyof typeof STAGES)[]).map(k => <li key={k} className={job.stages[k].status}><span>{STAGES[k]}</span><span>{job.stages[k].status === "pending" ? "Waiting" : job.stages[k].message || job.stages[k].status}</span></li>)}</ol>}
    {phase === "working" && !busy && <div className="section-toolbar"><button onClick={() => setPhase("upload")}>Start again</button></div>}
    <Feedback message={error} />
  </section>;

  if (phase === "review" && review && draft && prefill) {
    const moving = draft.parsed.joints.filter(j => j.type !== "fixed");
    const adapterIssues = generated?.status === "needs_information" ? generated.issues : [];
    const issues = [...prefill.issues, ...(result?.mapping?.issues ?? []), ...adapterIssues.map(i => ({ ...i, message: "Control adapter: " + i.message }))];
    const functions = driver?.definition.functions ?? [];
    return <section className="config-card auto-setup" aria-label="Review the AI setup">
      <h3>Review {review.name}</h3>
      <p>Every value is filled in. Badges show where each came from: <Badge p={{ source: "urdf" }} /> <Badge p={{ source: "documentation" }} /> <Badge p={{ source: "derived" }} /> <Badge p={{ source: "default" }} />. Hover a badge to see the quote or reason. Defaults need your attention most.</p>
      {!!issues.length && <ul className="issue-list" aria-label="Problems to resolve">{issues.map((i, n) => <li key={n}>{i.message}</li>)}</ul>}
      <div className="configuration-grid">
        <label className="field">Robot name<input aria-label="Robot name" value={review.name} disabled={locked} onChange={e => setReview({ ...review, name: e.target.value })} /><Badge p={source("name")} /></label>
        <label className="field">Robot ID<input aria-label="Robot ID" value={review.id} disabled={locked} onChange={e => setReview({ ...review, id: e.target.value })} />{errors.id && <small className="field-issue">{errors.id}</small>}</label>
        <label className="field">Manufacturer<input aria-label="Manufacturer" value={review.manufacturer} disabled={locked} onChange={e => setReview({ ...review, manufacturer: e.target.value })} /><Badge p={source("manufacturer")} /></label>
        <label className="field">Tool link<select aria-label="Tool link" value={review.tool_link ?? ""} disabled={locked} onChange={e => setReview({ ...review, tool_link: e.target.value || null })}><option value="">Choose the tool link</option>{draft.parsed.links.map(l => <option key={l}>{l}</option>)}</select><Badge p={source("tool_link")} />{errors.tool_link && <small className="field-issue">{errors.tool_link}</small>}</label>
        <label className="field">Payload (kg)<input aria-label="Payload" type="number" min="0" step="any" value={review.payload_kg ?? ""} placeholder="Unrated" disabled={locked} onChange={e => setReview({ ...review, payload_kg: num(e.target.value) })} /><Badge p={source("payload_kg")} /></label>
      </div>
      <label className="field">Description<textarea aria-label="Robot description" value={review.description} disabled={locked} onChange={e => setReview({ ...review, description: e.target.value })} /><Badge p={source("description")} /></label>
      <h4>Joints</h4>
      <div className="urdf-joint-table"><table className="review-table" aria-label="Joint values"><thead><tr><th>Joint</th><th>Minimum</th><th>Maximum</th><th>Speed</th><th>Acceleration</th><th>Start</th></tr></thead><tbody>
        {moving.map(j => { const unit = j.type === "prismatic" ? "m" : "rad"; return <tr key={j.name}><th scope="row"><code>{j.name}</code><small>{j.type} · {unit}</small>{j.type === "continuous" && <small>Wheel: rotation window, not a stop</small>}</th>
          {FIELDS.map(f => { const key = `joints.${j.name}.${f}`, p = source(key); return <td key={f} className={errors[key] ? "has-error" : ""}>
            <input aria-label={`${j.name} ${f}`} type="number" step="any" min={f === "velocity" || f === "acceleration" ? 0 : undefined} value={review.joints[j.name]?.[f] ?? ""} readOnly={p?.source === "urdf"} disabled={locked} onChange={e => setJoint(j.name, f, e.target.value)} />
            <small>{unit}{f === "velocity" ? "/s" : f === "acceleration" ? "/s²" : ""}</small><Badge p={p} />{errors[key] && <small className="field-issue">{errors[key]}</small>}</td>; })}</tr>; })}
      </tbody></table></div>
      {review.gripper_actuator && <p>Gripper: <code>{review.gripper_actuator}</code> closed at {fmt(review.gripper_closed)}, open at {fmt(review.gripper_open)}. <Badge p={source("gripper")} />{errors.gripper && <small className="field-issue">{errors.gripper}</small>}</p>}
      {mobility && mobility.classification !== "STATIONARY" && <><h4>{mobility.classification === "BOTH" ? "Mobile base with arm" : "Mobile base"}</h4>
        <p>Left wheel <code>{mobility.left_wheel}</code>, right wheel <code>{mobility.right_wheel}</code>. <Badge p={source("mobility.classification")} /></p>
        <div className="configuration-grid">{MOBILE_FIELDS.map(([k, label]) => <label className="field" key={k}>{label}<input aria-label={label} type="number" min="0" step="any" value={Number(mobility[k] ?? 0)} disabled={locked} onChange={e => setMobility({ ...mobility, [k]: Number(e.target.value) })} /><Badge p={source("mobility." + k)} /></label>)}</div>
        <div className="coordinate-grid">{["Min X", "Min Y", "Max X", "Max Y"].map((label, n) => <label className="field" key={label}>Drive area {label} (m)<input type="number" step="any" value={Number((mobility.navigation_bounds as number[] | undefined)?.[n] ?? 0)} disabled={locked} onChange={e => { const b = [...(mobility.navigation_bounds as number[])]; b[n] = Number(e.target.value); setMobility({ ...mobility, navigation_bounds: b }); }} /></label>)}<Badge p={source("mobility.navigation_bounds")} /></div></>}
      <h4>Control adapter</h4>
      {generated?.status === "simulator" && <p>No documentation was given, so a simulator adapter with one function per joint is made when you accept.</p>}
      {generated?.status === "needs_information" && !driver && <><p className="inline-note">The AI model's adapter was incomplete. Fix the rows below and save the table; the mapping is then proposed again.</p>
        <GeneratedFunctions draft={generated.draft} issues={generated.issues} disabled={locked} onSaved={d => { setDriver(d); setRows([]); setNotice("Adapter saved from the table. The mapping is proposed when you accept."); }} /></>}
      {driver && <><table className="review-table" aria-label="Control functions"><thead><tr><th>Function</th><th>Vendor method</th><th>Mode</th><th>Range</th><th>Evidence</th></tr></thead><tbody>
        {driver.definition.functions.map(f => <tr key={f.id}><td><code>{f.id}</code></td><td><code>{f.vendor_method}</code></td><td>{f.mode}</td><td>{f.minimum} to {f.maximum} {f.unit}</td><td><span className="source-badge documentation" title={f.documentation_quote}>Quote</span></td></tr>)}</tbody></table>
        <small>Generated by {driver.provenance?.model ?? "the AI model"} from the documentation. Each function's numbers appear in its quote. It is reviewed and tested in simulation when you accept.</small></>}
      {!!rows.length && <><h4>Joint mapping</h4><table className="review-table" aria-label="Joint mapping"><thead><tr><th>Joint</th><th>Name</th><th>Function</th><th>Scale (from units)</th></tr></thead><tbody>
        {rows.map((r, n) => <tr key={r.joint_id}><td><code>{r.joint_id}</code></td><td><input aria-label={`Name for ${r.joint_id}`} value={r.alias} disabled={locked} onChange={e => setRows(rows.map((x, i) => i === n ? { ...x, alias: e.target.value } : x))} /></td>
          <td className={errors[`mapping.${r.joint_id}`] ? "has-error" : ""}>{r.role === "independent" ? <select aria-label={`Function for ${r.joint_id}`} value={r.function_id ?? ""} disabled={locked} onChange={e => setRows(rows.map((x, i) => i === n ? { ...x, function_id: e.target.value || null } : x))}><option value="">Choose a function</option>{functions.map(f => <option key={f.id} value={f.id}>{f.id} · {f.unit}</option>)}</select> : <small>{r.role}</small>}</td>
          <td>{fmt(r.scale)}</td></tr>)}</tbody></table>
        {generated?.status === "complete" && rows.some(r => r.role === "independent" && !r.function_id) && <div className="section-toolbar"><button disabled={locked} onClick={() => void remap()}><Sparkles size={14} /> Propose mapping again</button></div>}
        <small>Scales are worked out from the units (metres to millimetres is 1000, radians to degrees is 57.2958). If you change a function, check the scale in manual setup.</small></>}
      {(!!prefill.notes.length || !!result?.mapping?.notes.length) && <details><summary>AI values that were checked and set aside ({prefill.notes.length + (result?.mapping?.notes.length ?? 0)})</summary><ul>{[...prefill.notes, ...(result?.mapping?.notes ?? [])].map((n, i) => <li key={i}>{n}</li>)}</ul></details>}
      <div className="section-toolbar"><button className="primary" disabled={locked || (generated?.status === "needs_information" && !driver) || rows.some(r => r.role === "independent" && !r.function_id && !!driver)} onClick={() => void accept()}>{busy || "Accept and build robot"}</button><button disabled={locked} onClick={onCancel}>Cancel</button></div>
      {rows.some(r => r.role === "independent" && !r.function_id && !!driver) && <p className="field-issue">Choose a function for every joint before building.</p>}
      <Feedback message={error} />{notice && <p className="inline-note" role="status">{notice}</p>}
    </section>;
  }

  if (phase === "try" && model && binding && driver) {
    const independent = rows.filter(r => r.role === "independent" && r.function_id);
    const tested = binding.test_evidence.actuators?.tested_joints ?? [];
    const allTried = independent.every(r => tested.includes(r.joint_id));
    const wrong = independent.filter(r => checks[r.joint_id] === "wrong"), unchecked = independent.filter(r => !checks[r.joint_id]);
    const moveOk = !!binding.test_evidence.move?.passed;
    const ready = allTried && moveOk && !wrong.length && !unchecked.length;
    return <section className="config-card auto-setup" aria-label="Try the generated functions">
      <h3>Try {model.robot.name}'s functions</h3>
      <p className="inline-note">Simulation only: each button runs the generated adapter code against a simulated SDK. No hardware is contacted.</p>
      <div className="section-toolbar"><button className="primary" disabled={locked} onClick={() => void tryAll()}>{busy === "Trying every function…" ? busy : "Try every function"}</button><small>Runs each function to its limits in turn while you watch the robot.</small></div>
      <div className="try-layout"><div className="mapping-preview"><Canvas camera={{ position: [1.4, 1.2, 1.4], near: .001 }}><ambientLight intensity={1.5} /><directionalLight position={[2, 3, 2]} intensity={2} /><Robot model={model} q={q} /><Grid args={[4, 4]} cellSize={.1} sectionSize={.5} fadeDistance={6} /><OrbitControls makeDefault target={[0, .3, 0]} /></Canvas></div>
        <div className="function-cards">{independent.map(r => { const f = functionOf(r), spec = model.actuators.actuators[r.joint_id], velocity = f?.mode === "velocity";
          const tries = triesFor(r);
          return <article key={r.joint_id} className={`function-card ${checks[r.joint_id] ?? ""}`}><h4>{r.alias || r.joint_id}</h4>
            <small><code>{r.joint_id}</code> → <code>{f?.vendor_method ?? f?.id}</code> · {f?.minimum} to {f?.maximum} {f?.unit}</small>
            <div className="section-toolbar">{tries.map(([label, value]) => <button key={label} disabled={locked} onClick={() => void tryValue(r, value, label)}>{label} ({fmt(value)} {spec.unit}{velocity ? "/s" : ""})</button>)}</div>
            <small>{results[r.joint_id] ?? (tested.includes(r.joint_id) ? "Tried" : "Not tried yet")}</small>
            <div className="section-toolbar"><button aria-pressed={checks[r.joint_id] === "works"} disabled={locked || !tested.includes(r.joint_id)} onClick={() => mark(r.joint_id, "works")}>Works as expected</button><button aria-pressed={checks[r.joint_id] === "wrong"} disabled={locked || !tested.includes(r.joint_id)} onClick={() => mark(r.joint_id, "wrong")}>Wrong</button></div>
          </article>; })}</div></div>
      <h4>MOVE</h4><MotionWorkerSetup disabled={locked} />
      <div className="coordinate-grid"><label className="field">Move<select aria-label="MOVE target" value={move.target} onChange={e => setMove({ ...move, target: e.target.value })}>{mobility?.classification !== "MOVING" && <option value="tool">Tool</option>}{mobility && mobility.classification !== "STATIONARY" && <option value="base">Mobile base</option>}</select></label>
        {(["x", "y", "z"] as const).filter(k => move.target !== "base" || k !== "z").map(k => <label className="field" key={k}>{k.toUpperCase()} (m)<input aria-label={`MOVE ${k.toUpperCase()}`} type="number" step="any" value={move[k]} onChange={e => setMove({ ...move, [k]: Number(e.target.value) })} /></label>)}</div>
      <div className="section-toolbar"><button disabled={locked} onClick={() => void testMove()}>Compile & test MOVE</button></div>
      <ul className="readiness" aria-label="Readiness">
        <li className="ok">Adapter reviewed and passed its simulated tests</li>
        <li className={allTried ? "ok" : "todo"}>Functions tried: {independent.filter(r => tested.includes(r.joint_id)).length} / {independent.length}</li>
        <li className={!unchecked.length && !wrong.length ? "ok" : "todo"}>{wrong.length ? `Marked wrong: ${wrong.map(r => r.alias || r.joint_id).join(", ")}` : `Checked: ${independent.length - unchecked.length} / ${independent.length}`}</li>
        <li className={moveOk ? "ok" : "todo"}>{moveOk ? "MOVE tested" : "MOVE test required"}</li></ul>
      {!!wrong.length && <p className="field-issue">A function marked wrong needs fixing before saving. Open this robot from "Resume setup" in the step-by-step wizard to change its mapping or scale.</p>}
      <label className="check-field"><input type="checkbox" checked={reviewed} disabled={locked} onChange={e => setReviewed(e.target.checked)} />I reviewed the values, the adapter functions and the mapping.</label>
      <div className="section-toolbar"><button className="primary" disabled={locked || !ready || !reviewed} onClick={() => void save()}>{busy || "Save robot"}</button><button disabled={locked} onClick={onDone}>Finish later</button></div>
      <Feedback message={error} />{notice && <p className="inline-note" role="status">{notice}</p>}
    </section>;
  }
  return null;
}

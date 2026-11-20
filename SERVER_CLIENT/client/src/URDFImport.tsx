import { useEffect, useRef, useState } from "react";
import { Upload, Sparkles, Check, Download } from "lucide-react";
import { api, post, download, ApiError } from "./api";
import type { LLMConfiguration, Model } from "./types";
import Feedback from "./ui/Feedback";
import "./ui/auto-setup.css";

type Joint = { name: string; type: string; parent: string; child: string; axis: number[];
  origin: { xyz: number[]; rpy: number[] }; min: number | null; max: number | null;
  velocity: number | null; acceleration: number | null; effort: number | null };
type Settings = Record<"min" | "max" | "velocity" | "acceleration" | "initial", string>;
type Suggestion = { name: string; manufacturer: string; manufacturer_evidence?: string; description: string; tool_link: string | null;
  capability_suggestions: string[]; notes: string[];
  command_mappings: { joint: string; vendor_command: string; evidence: string }[] };
type Draft = { id: string; filename: string; urdf_path: string; sha256: string;
  parsed: { name: string; base_link: string; links: string[]; tips: string[]; joints: Joint[]; unsupported: string[] };
  meshes: { uri: string; status: string; path: string | null }[]; suggestion: Suggestion | null;
  provenance: { adapter_id: string; adapter_version: number; model: string } | null };
type Validation = { bundle: unknown; planning_supported: boolean; provenance: { warnings: string[] } };
const titles = { min: "Minimum", max: "Maximum", velocity: "Velocity", acceleration: "Acceleration", initial: "Initial position" };

export default function URDFImport({ disabled, onStage, onSaved, onBusy }: {
  disabled: boolean; onBusy: (busy: boolean) => void; onStage: (review: boolean) => void; onSaved: (model: Model) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null), [path, setPath] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null), [joints, setJoints] = useState<Record<string, Settings>>({});
  const [id, setId] = useState(""), [name, setName] = useState(""), [manufacturer, setManufacturer] = useState(""),
    [description, setDescription] = useState(""), [tool, setTool] = useState(""), [payload, setPayload] = useState("");
  const [gripper, setGripper] = useState(""), [closed, setClosed] = useState(""), [open, setOpen] = useState("");
  const [providers, setProviders] = useState<LLMConfiguration>({ default_id: null, adapters: [] }),
    [provider, setProvider] = useState(""), [documentation, setDocumentation] = useState("");
  const [busy, setBusy] = useState(""), [error, setError] = useState(""), [accepted, setAccepted] = useState(false),
    [reviewed, setReviewed] = useState(false), [validated, setValidated] = useState<Validation | null>(null),
    [validatedInput, setValidatedInput] = useState("");
  const [coupling,setCoupling]=useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({}), [filled, setFilled] = useState("");
  const currentDraft = useRef<string | null>(null);
  useEffect(() => {
    void api<LLMConfiguration>("/llm/adapters").then(setProviders).catch(e => setError(e.message));
    return () => { if (currentDraft.current) void api(`/registry/urdf/drafts/${currentDraft.current}`, { method: "DELETE" }).catch(() => {}); };
  }, []);
  const locked = disabled || !!busy;
  const work = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); onBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(""); onBusy(false); }
  };
  const settings = {
    id, name, manufacturer, description, tool_link: tool, review_coupling:coupling,
    joints: Object.fromEntries(Object.entries(joints).map(([key, values]) => [key,
      Object.fromEntries(Object.entries(values).map(([field, value]) => [field, value.trim() === "" ? null : Number(value)]))])),
    payload_kg: payload.trim() === "" ? null : Number(payload),
    gripper_actuator: gripper || null, gripper_closed: closed.trim() === "" ? null : Number(closed),
    gripper_open: open.trim() === "" ? null : Number(open), reviewed,
  };
  // Checking the review box does not change the validated robot definition.
  const signature = JSON.stringify({ ...settings, reviewed: false });
  const valid = !!validated && signature === validatedInput;
  const changed = () => setReviewed(false);
  /** Fills every empty value from the URDF and, if pasted below, the documentation; extracted URDF values stay as they are. */
  const fill = () => void work("Filling in values…", async () => {
    if (!draft) return;
    type Filled = { review: { name: string; manufacturer: string; description: string; tool_link: string | null; payload_kg: number | null;
      gripper_actuator: string | null; gripper_closed: number | null; gripper_open: number | null; joints: Record<string, Record<keyof Settings, number | null>> };
      provenance: Record<string, { source: string }>; notes: string[] };
    const r = await post<Filled>(`/registry/urdf/drafts/${draft.id}/autofill`, { adapter_id: provider || null, documentation });
    const text = (v: number | null) => (v === null ? "" : String(v));
    setJoints(prev => Object.fromEntries(Object.entries(prev).map(([joint, values]) => [joint, Object.fromEntries(Object.entries(values).map(([field, value]) =>
      [field, value.trim() === "" ? text(r.review.joints[joint]?.[field as keyof Settings] ?? null) : value])) as Settings])));
    if (!tool && r.review.tool_link) setTool(r.review.tool_link);
    if (!description && r.review.description) setDescription(r.review.description);
    if (!manufacturer && r.review.manufacturer) setManufacturer(r.review.manufacturer);
    if (!payload && r.review.payload_kg !== null) setPayload(String(r.review.payload_kg));
    if (!gripper && r.review.gripper_actuator) { setGripper(r.review.gripper_actuator); setClosed(text(r.review.gripper_closed)); setOpen(text(r.review.gripper_open)); }
    const defaults = Object.values(r.provenance).filter(p => p.source === "default").length, documented = Object.values(r.provenance).filter(p => p.source === "documentation").length;
    setFilled(`Filled in from the URDF${documented ? ` and ${documented} documented values` : ""}. ${defaults} defaults need review: continuous-joint windows (±1000 rad), accelerations (full speed in 0.5 s) and starting positions.`);
    setFieldErrors({}); changed();
  });
  if (!draft) return <section className="config-card urdf-import">
    <h3>1. Import URDF and meshes</h3>
    <p>Upload an expanded <strong>.urdf</strong> or a <strong>.zip</strong> containing the URDF and its meshes.
      Joint structure is parsed directly. Optional LLM assistance adds reviewable metadata suggestions.</p>
    <label className="field">Robot source file<input type="file" accept=".urdf,.zip" aria-label="URDF source file" disabled={locked}
      onChange={e => { setFile(e.target.files?.[0] ?? null); setError(""); }} /></label>
    <label className="field">URDF path inside ZIP · optional<input aria-label="URDF path in ZIP" value={path} disabled={locked}
      placeholder="robot_description/urdf/robot.urdf" onChange={e => setPath(e.target.value)} />
      <small>Needed when the package contains several URDF files.</small></label>
    <p className="inline-note">Maximum 32 MB upload; 100 MB expanded. Xacro must be expanded before upload.
      Files stay on this backend. Uploading does not add a robot, execute code, fetch external meshes, or connect hardware.</p>
    <button className="primary" disabled={locked || !file} onClick={() => void work("Reading URDF…", async () => {
      if (!file) return;
      if (file.size > 32 * 1024 * 1024) throw new Error("URDF upload must be at most 32 MB");
      const d = await api<Draft>(`/registry/urdf/drafts?filename=${encodeURIComponent(file.name)}&urdf_path=${encodeURIComponent(path)}`,
        { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
      currentDraft.current = d.id; setDraft(d);
      setName(d.parsed.name); setId(d.parsed.name.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^[^a-z]+/, "") || "imported_robot");
      setTool(d.parsed.tips.length === 1 ? d.parsed.tips[0] : "");
      setJoints(Object.fromEntries(d.parsed.joints.filter(j => j.type !== "fixed").map(j => [j.name, {
        min: j.min === null ? "" : String(j.min), max: j.max === null ? "" : String(j.max),
        velocity: j.velocity === null ? "" : String(j.velocity), acceleration: j.acceleration === null ? "" : String(j.acceleration),
        initial: (j.min === null || j.min <= 0) && (j.max === null || j.max >= 0) ? "0" : "",
      }])));
      onStage(true);
    })}><Upload size={14} /> {busy || "Read URDF"}</button>
    <Feedback message={error} />
  </section>;

  const moving = draft.parsed.joints.filter(j => j.type !== "fixed");
  return <section className="config-card urdf-import" aria-label="URDF robot review">
    <h3>2. Review imported robot</h3>
    <p><strong>{draft.parsed.name}</strong> · {draft.parsed.links.length} links · {moving.length} moving joints · {draft.urdf_path}</p>
    <p className="inline-note">Extracted values are read-only. Fill every missing limit/rate and review initial positions.
      Default zero positions are proposals until you confirm them. No acceleration or payload rating is inferred.</p>
    {!!draft.parsed.unsupported.length && <div className="urdf-blockers" role="alert"><strong>Import blocked</strong>
      <ul>{draft.parsed.unsupported.map((item, i) => <li key={i}>{item}</li>)}</ul>
      <p>The source remains unchanged. Supply a supported URDF or integrate its joint coupling before importing.</p></div>}
    <div className="configuration-grid">
      <label className="field">Global robot ID<input aria-label="URDF robot ID" value={id} disabled={locked} onChange={e => { setId(e.target.value); changed(); }} /></label>
      <label className="field">Robot name<input aria-label="URDF robot name" value={name} disabled={locked} onChange={e => { setName(e.target.value); changed(); }} /></label>
      <label className="field">Manufacturer · optional<input aria-label="URDF manufacturer" value={manufacturer} disabled={locked} onChange={e => { setManufacturer(e.target.value); changed(); }} /></label>
      <label className="field">End-effector link<select aria-label="URDF tool link" value={tool} disabled={locked} onChange={e => { setTool(e.target.value); changed(); }}>
        <option value="">Select a link</option>{draft.parsed.links.map(link => <option key={link}>{link}</option>)}</select></label>
    </div>
    <label className="field">Description<textarea aria-label="URDF description" value={description} disabled={locked} onChange={e => { setDescription(e.target.value); changed(); }} /></label>
    <div className="section-toolbar"><h4>Joint configuration</h4><button disabled={locked} onClick={fill}><Sparkles size={14} /> Fill in missing values</button></div>
    {filled && <p className="inline-note" role="status">{filled}</p>}
    <div className="urdf-joint-table"><table><thead><tr><th>Joint</th>{Object.entries(titles).map(([key, title]) => <th key={key}>{title}</th>)}</tr></thead>
      <tbody>{moving.map(joint => <tr key={joint.name}><th scope="row"><strong>{joint.name}</strong><small>{joint.type} · {joint.type === "prismatic" ? "m" : "rad"}</small>
        {joint.type === "continuous" && <small>Wheel: a rotation window, not a stop (for example -1000 to 1000, start 0)</small>}</th>
        {(Object.keys(titles) as (keyof Settings)[]).map(field => {
          const extracted = field !== "initial" && joint[field] !== null;
          const issue = fieldErrors[`joints.${joint.name}.${field}`];
          return <td key={field} className={issue ? "has-error" : ""}><input aria-label={`URDF ${joint.name} ${field}`} type="number" step="any" min={field === "velocity" || field === "acceleration" ? 0 : undefined} value={joints[joint.name]?.[field] ?? ""}
            readOnly={extracted} disabled={locked} placeholder="Required" onChange={e => {
              const value=e.currentTarget.value;
              setJoints(prev => ({ ...prev, [joint.name]: { ...prev[joint.name], [field]: value } })); changed();
              setFieldErrors(e => { const n = { ...e }; delete n[`joints.${joint.name}.${field}`]; return n; });
            }} /><small>{joint.type === "prismatic" ? "m" : "rad"}{field === "velocity" ? "/s" : field === "acceleration" ? "/s²" : ""}</small><small>{extracted ? (field === "acceleration" ? "URDF extension" : "Extracted from URDF") : field === "initial" ? "Review starting value" : (joints[joint.name]?.[field] ? "User configured" : "Needs configuration")}</small>{issue && <small className="field-issue">{issue}</small>}</td>;
        })}</tr>)}</tbody></table></div>
    <details><summary>Extracted frames, axes and source values</summary><pre className="urdf-extracted" aria-label="Extracted URDF structure">{JSON.stringify(draft.parsed.joints, null, 2)}</pre></details>
    <details><summary>Optional payload and gripper configuration</summary>
      <p>A missing payload stays explicitly unrated. Gripper endpoints must be configured from your documentation; they are not inferred.</p>
      <div className="configuration-grid">
        <label className="field">Verified payload · kg<input type="number" min="0" step="any" aria-label="URDF payload" value={payload} disabled={locked}
          onChange={e => { setPayload(e.target.value); changed(); }} /></label>
        <label className="field">Gripper actuator<select aria-label="URDF gripper actuator" value={gripper} disabled={locked} onChange={e => { setGripper(e.target.value); changed(); }}>
          <option value="">Not configured</option>{moving.map(j => <option key={j.name}>{j.name}</option>)}</select></label>
        {gripper && <><label className="field">Closed position · joint units<input aria-label="URDF gripper closed" type="number" step="any" value={closed} disabled={locked}
          onChange={e => { setClosed(e.target.value); changed(); }} /></label>
          <label className="field">Open position · joint units<input aria-label="URDF gripper open" type="number" step="any" value={open} disabled={locked}
            onChange={e => { setOpen(e.target.value); changed(); }} /></label></>}
      </div>
    </details>
    <details><summary>Optional LLM assistance</summary>
      <p>Use an AI model to suggest labels, descriptions and documentation-backed command mappings. Suggestions cannot change extracted geometry or limits, enable hardware, or activate capabilities.</p>
      <label className="field">LLM adapter<select aria-label="URDF LLM adapter" value={provider} disabled={locked} onChange={e => setProvider(e.target.value)}>
        <option value="">{providers.default_id ? "Workspace default" : "Choose an AI model"}</option>
        {providers.adapters.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      {!providers.adapters.length && <p className="inline-note">Add an AI model in Configuration → AI Models for suggestions. Manual URDF conversion remains available.</p>}
      <label className="field">Vendor documentation · optional<textarea aria-label="URDF vendor documentation" maxLength={60000} value={documentation} disabled={locked}
        onChange={e => setDocumentation(e.target.value)} /></label>
      <button disabled={locked || (!provider && !providers.default_id)} onClick={() => void work("Requesting suggestions…", async () => {
        const next = await post<Draft>(`/registry/urdf/drafts/${draft.id}/suggest`, { adapter_id: provider || null, documentation });
        setDraft(next); setAccepted(false); setReviewed(false);
      })}><Sparkles size={14} /> {busy || "Suggest robot metadata"}</button>
      {draft.suggestion && <div className="urdf-suggestions" aria-label="LLM robot suggestions">
        <h4>{accepted ? "Accepted suggestions · review before saving" : "Suggestions · not applied"}</h4>
        <p>{draft.suggestion.name} {draft.suggestion.manufacturer && ` · ${draft.suggestion.manufacturer}`}</p>
        <p>{draft.suggestion.description}</p>
        {draft.suggestion.manufacturer_evidence && <p>Manufacturer evidence: {draft.suggestion.manufacturer_evidence}</p>}
        {draft.suggestion.tool_link && <p>Proposed tool link: <code>{draft.suggestion.tool_link}</code></p>}
        <ul>{draft.suggestion.capability_suggestions.map((s, i) => <li key={i}>Capability suggestion: {s} · advisory only</li>)}
          {draft.suggestion.notes.map((s, i) => <li key={i}>{s}</li>)}</ul>
        {draft.suggestion.command_mappings.map((mapping, i) => <p key={i}><code>{mapping.joint} → {mapping.vendor_command}</code><br />Evidence: {mapping.evidence}<br />Reference only; configure and test the control adapter separately.</p>)}
        <small>Generated by {draft.provenance?.model} · adapter version {draft.provenance?.adapter_version}</small>
        <button disabled={locked} onClick={() => {
          const s = draft.suggestion!; if (s.name) setName(s.name); if (s.manufacturer) setManufacturer(s.manufacturer);
          if (s.description) setDescription(s.description); if (!tool && s.tool_link) setTool(s.tool_link);
          setAccepted(true); changed();
        }}>Use suggested metadata</button>
      </div>}
    </details>
    <details><summary>Retained source and mesh references</summary>
      <p>Original {draft.filename} · URDF SHA-256 <code className="urdf-hash">{draft.sha256}</code></p>
      {draft.meshes.length ? <ul>{draft.meshes.map(m => <li key={m.uri}><code>{m.uri || "Unnamed mesh"}</code> · {m.status}{m.path ? ` → ${m.path}` : " · include its package for Isaac import"}</li>)}</ul> : <p>No external mesh references.</p>}
      <p>The built-in preview renders the kinematic structure. Original mesh materials, collisions and dynamics need separate native Isaac import and validation.</p>
    </details>
    <label className="check-row"><input type="checkbox" checked={coupling} disabled={locked} onChange={e=>setCoupling(e.target.checked)}/>Review imported mimic joints as coupled joints in the mapping wizard; they must never receive independent setters.</label>
    <div className="section-toolbar"><button className="secondary" disabled={locked || draft.parsed.unsupported.some(reason=>!coupling||!reason.includes("mimic coupling"))} onClick={() => void work("Validating robot…", async () => {
      setValidated(null); setFieldErrors({});
      let result: Validation;
      try { result = await post<Validation>(`/registry/urdf/drafts/${draft.id}/validate`, settings); }
      catch (e) {
        if (e instanceof ApiError && e.errors.length) { setFieldErrors(Object.fromEntries(e.errors.map(x => [x.field, x.message]))); throw new Error(`${e.errors.length} value${e.errors.length > 1 ? "s need" : " needs"} attention; each is marked in the table.`); }
        throw e;
      }
      setValidated(result); setValidatedInput(signature); setReviewed(false);
    })}><Check size={14} /> Validate robot definition</button>
      {valid && <button disabled={locked} onClick={() => download(`${id}.robot.json`, JSON.stringify(validated.bundle, null, 2))}><Download size={14} /> Export converted definition</button>}
    </div>
    {valid && <div className="urdf-validation" role="status"><strong>Definition validated · {validated.planning_supported ? "serial-chain IK available" : "configuration only"}</strong>
      <ul>{validated.provenance.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>}
    <label className="check-row"><input type="checkbox" aria-label="I reviewed the URDF robot configuration" checked={reviewed} disabled={locked || !valid}
      onChange={e => setReviewed(e.target.checked)} /> I reviewed the extracted values, starting positions, configured limits and preview limitations.</label>
    <button className="primary" disabled={locked || !valid || !reviewed} onClick={() => void work("Saving global robot…", async () => {
      const model = await post<Model>(`/registry/urdf/drafts/${draft.id}/commit`, settings); await onSaved(model);
    })}>{busy || "Save global robot & continue"}</button>
    <Feedback message={error} />
  </section>;
}

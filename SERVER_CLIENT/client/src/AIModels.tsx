import { lazy, Suspense, useEffect, useState } from "react";
import { Play, Plus, RefreshCw, Save, Star, Trash2 } from "lucide-react";
import { api, download, post } from "./api";
import nebiusCode from "../../server/examples/llm/nebius_token_factory.py?raw";
import hostedCode from "../../server/examples/llm/hosted_chat.py?raw";
import sampleCode from "../../server/examples/llm/ollama_adapter.py?raw";
import NvidiaLogo from "./branding/NvidiaLogo";
import type { LLMAdapter, LLMConfiguration, RoleSettings } from "./types";
import { useMode } from "./mode";
import Feedback from "./ui/Feedback";
const AdapterCodeEditor = lazy(() => import("./CodeView").then((m) => ({ default: m.AdapterCodeEditor })));

type Kind = "ollama" | "openai" | "nebius" | "gemini" | "nvidia" | "custom";
type Status = { available: boolean | null; message: string; models: string[] };
const kinds: Record<Kind, string> = { ollama: "Ollama", gemini: "Google Gemini", nvidia: "NVIDIA API · Nemotron", nebius: "Nebius Token Factory", openai: "OpenAI-compatible API", custom: "Custom Python function" };
const addresses: Record<Kind, string> = { ollama: "http://localhost:11434/v1", openai: "", nebius: "https://api.tokenfactory.nebius.com/v1", gemini: "https://generativelanguage.googleapis.com/v1beta/openai", nvidia: "https://integrate.api.nvidia.com/v1", custom: "http://localhost:11434" };
const hosted: Partial<Record<Kind, { label: string; environment: string; code: string; file: string; description: string; url: string; link: string }>> = {
  nebius: {label:"Independent Nebius adapter",environment:"NEBIUS_API_KEY",code:nebiusCode,file:"nebius_token_factory.py",description:"Hosted LLM inference through Nebius Token Factory. Works with any robot or simulator in every RoboDE edition; no GPU VM is required.",url:"https://tokenfactory.nebius.com/",link:"Open Token Factory"},
  gemini: {label:"Independent Gemini adapter",environment:"GEMINI_API_KEY",code:hostedCode,file:"gemini_adapter.py",description:"Google-hosted Gemini inference using a Google AI Studio API key. Independent of robot adapters, simulator selection and GCP VM configuration.",url:"https://aistudio.google.com/apikey",link:"Google AI Studio keys"},
  nvidia: {label:"Independent NVIDIA adapter",environment:"NVIDIA_API_KEY",code:hostedCode,file:"nvidia_api_adapter.py",description:"NVIDIA-hosted inference at integrate.api.nvidia.com, including Nemotron models. This uses an NVIDIA API key; local Ollama and Isaac Sim connections are separate. No robot GPU VM is required.",url:"https://build.nvidia.com/",link:"NVIDIA API catalog & keys"},
};
const fresh = { name: "", connection_type: "ollama" as Kind, base_url: addresses.ollama, model: "", source_code: sampleCode, timeout_seconds: 120,
  max_tokens: 4096, supports_vision: false, structured_outputs: true, api_key_env: "" };

/** Same inference as the backend, for profiles saved before connection types existed. */
export function kindOf(p: Pick<LLMAdapter, "protocol" | "base_url"> & { connection_type?: Kind | null }): Kind {
  if (p.connection_type && p.connection_type !== "openai") return p.connection_type;
  if (p.protocol === "python_function") return p.connection_type ?? "custom";
  try { const host = new URL(p.base_url).hostname;
    if(host === "generativelanguage.googleapis.com") return "gemini";
    if(host === "integrate.api.nvidia.com") return "nvidia";
  } catch { /* An unsaved API address can be incomplete. */ }
  if(p.connection_type) return p.connection_type;
  return /:11434(\/|$)|ollama/.test(p.base_url) ? "ollama" : "openai";
}
export const isNemotron = (model: string) => /nemotron/i.test(model);
const roleLabels = [["planner_adapter_id", "Planner LLM"], ["binding_adapter_id", "Task LLM"]] as const;

export default function AIModels({ providers, disabled, onSaved }: { providers: LLMConfiguration; disabled: boolean; onSaved: () => Promise<void> | void }) {
  const { expert } = useMode();
  const [edit, setEdit] = useState<string | null>(providers.default_id ?? providers.adapters[0]?.id ?? null);
  const [form, setForm] = useState(fresh), [key, setKey] = useState(""), [clearKey, setClearKey] = useState(false);
  const [found, setFound] = useState<string[] | null>(null), [statuses, setStatuses] = useState<Record<string, Status | "checking">>({});
  const [roles, setRoles] = useState<RoleSettings>({ vision_enabled: false });
  const [input, setInput] = useState("Reply with a short greeting."), [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const locked = busy || disabled;
  const work = async (fn: () => Promise<void>) => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const check = async (id: string) => {
    setStatuses((s) => ({ ...s, [id]: "checking" }));
    const status = await api<Status>(`/llm/adapters/${id}/status`).catch((e) => ({ available: false, message: (e as Error).message, models: [] }));
    setStatuses((s) => ({ ...s, [id]: status }));
  };
  useEffect(() => { void api<RoleSettings>("/llm/roles").then(setRoles).catch((e) => setError(e.message)); }, []);
  // Status checks only list models; they never download, load or start anything.
  useEffect(() => { providers.adapters.forEach((p) => { if (!statuses[p.id]) void check(p.id); }); }, [providers.adapters.map((p) => p.id).join()]);
  useEffect(() => {
    const p = providers.adapters.find((a) => a.id === edit);
    if (p) { setForm({ ...fresh, ...p, connection_type: kindOf(p), source_code: p.source_code || sampleCode }); setKey(""); setClearKey(false); setAnswer(""); setFound(null); }
  }, [edit, providers]);
  const selectedProfile = providers.adapters.find((p) => p.id === edit);
  const name = (id?: string | null) => providers.adapters.find((p) => p.id === (id || providers.default_id))?.name ?? "No AI model";
  const custom = roleLabels.filter(([k]) => roles[k] && roles[k] !== providers.default_id);
  const setKind = (kind: Kind) => {
    setFound(null);setAnswer("");setError("");setNotice("");
    const preset=hosted[kind];
    const base_url=preset?addresses[kind]:kind==="custom"?form.base_url:Object.values(addresses).includes(form.base_url)?addresses[kind]:form.base_url;
    // Never carry an entered key to a different provider. A saved key is only
    // cleared when the edited connection is saved against the new endpoint.
    if(base_url!==form.base_url){setKey("");setClearKey(!!selectedProfile?.has_api_key);}
    setForm({...form,connection_type:kind,
      base_url,name:preset&&!form.name?kinds[kind]:form.name,
      model:kind!==form.connection_type&&kind!=="custom"&&form.connection_type!=="custom"?"":form.model,
      source_code:kind==="custom"&&hosted[form.connection_type]?hosted[form.connection_type]!.code:form.source_code,
      api_key_env:preset?preset.environment:kind==="custom"?form.api_key_env:hosted[form.connection_type]?"":form.api_key_env,
      structured_outputs:kind==="ollama"||preset?true:form.structured_outputs});
  };
  const hostedPreset=hosted[form.connection_type];
  const statusView = (id: string) => {
    const s = statuses[id];
    if (!s || s === "checking") return <span className="model-status unknown">Checking availability…</span>;
    const needsKey=s.message.startsWith("Enter your ")&&s.message.includes("API key");
    return <span className={`model-status ${needsKey?"unknown":s.available ? "ok" : s.available === false ? "bad" : "unknown"}`}>{needsKey?"API key needed":s.available ? "Available" : s.available === false ? "Unavailable" : "Not listed"}</span>;
  };
  return (
    <section className="config-card" aria-label="AI models">
      <div className="section-toolbar">
        <div><h3>AI Models</h3><p>AI connections run on the RoboDE backend. “Local Ollama” means Ollama on that backend machine.</p></div>
        <button aria-label="New AI connection" disabled={locked} onClick={() => { setEdit(null); setForm(fresh); setKey(""); setFound(null); setAnswer(""); }}><Plus size={15} /> New AI connection</button>
      </div>
      <Feedback message={error} />
      {notice && <p role="status" className="inline-note">{notice}</p>}
      <div className="effective-models" aria-label="Effective AI models">
        <strong>Workspace default: {name(providers.default_id)}</strong>
        {custom.length ? <><span className="tiny-tag">Custom AI settings</span>{custom.map(([k, label]) => <small key={k}>{label} uses {name(roles[k])} instead of the default.</small>)}</>
          : <small>The Planner LLM and Task LLM use the workspace default. Robot setup also uses the Task LLM.</small>}
        <small>Each plan can choose its own Planner LLM and Task LLM; single-task overrides appear in Expert mode.</small>
      </div>
      <section className="config-card planner-converter-settings" aria-label="AI model roles">
        <h3>Planner LLM and Task LLM</h3>
        <p>The Planner LLM turns your plan into tasks and assigns robots. The Task LLM turns each task into commands supported by that robot. Choose a model for each; they can be different models or connections.</p>
        <div className="configuration-grid">{roleLabels.map(([k, label]) => <label key={k} className="field">{label}
          <select aria-label={label} disabled={locked} value={roles[k] ?? ""} onChange={(e) => setRoles({ ...roles, [k]: e.target.value || null })}>
            <option value="">Workspace default</option>{providers.adapters.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.model}</option>)}
          </select></label>)}</div>
        <label className="check-field expert-only"><input type="checkbox" disabled={locked} checked={roles.vision_enabled} onChange={(e) => setRoles({ ...roles, vision_enabled: e.target.checked })} />Enable VLM planning. A vision-capable model and fresh scene image are required for every decomposition.</label>
        <button disabled={locked} onClick={() => void work(async () => { setRoles(await api<RoleSettings>("/llm/roles", { method: "PUT", body: JSON.stringify({planner_adapter_id:roles.planner_adapter_id??null,binding_adapter_id:roles.binding_adapter_id??null,vision_enabled:roles.vision_enabled}) })); await onSaved(); setNotice("Role settings saved. Revalidate affected plans."); })}>Save Planner & Task LLM</button>
      </section>
      <div className="ai-models">
        <div className="ai-model-list" aria-label="Configured AI models">
          {providers.adapters.map((p) => (
            <button key={p.id} className={edit === p.id ? "selected" : ""} disabled={busy} onClick={() => setEdit(p.id)}>
              <strong>{p.name}{providers.default_id === p.id && " · default"}</strong>
              <small>{kinds[kindOf(p)]} · {p.model}{isNemotron(p.model) && <span className="nemotron-tag">NVIDIA Nemotron</span>}</small>
              {statusView(p.id)}
            </button>
          ))}
          {!providers.adapters.length && <p>No AI connections yet. Add one to generate tasks and adapters.</p>}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); void work(async () => {
          const value = { ...Object.fromEntries(Object.keys(fresh).map((k) => [k, form[k as keyof typeof fresh]])),
            protocol: form.connection_type === "custom" ? "python_function" : "chat_completions",
            source_code: form.connection_type === "custom" ? form.source_code : "", api_key: key || null, clear_api_key: clearKey };
          const p = edit ? await api<LLMAdapter>(`/llm/adapters/${edit}`, { method: "PUT", body: JSON.stringify(value) }) : await post<LLMAdapter>("/llm/adapters", value);
          await onSaved(); setEdit(p.id); void check(p.id); setNotice("AI model saved. Recompile affected plans.");
        }); }}>
          <h3>{edit ? `Edit ${selectedProfile?.name ?? "AI model"}` : "Add AI connection"}</h3>
          {edit && statuses[edit] && statuses[edit] !== "checking" && <p className="inline-note" role="note">{(statuses[edit] as Status).message}</p>}
          <fieldset className="llm-setup-choice" disabled={locked}>
            <legend>Connection type</legend>
            {(Object.keys(kinds) as Kind[]).map((k) => <label key={k} className={k === "custom" ? "expert-only" : ""}><input type="radio" name="ai-connection" aria-label={kinds[k]} checked={form.connection_type === k} onChange={() => setKind(k)} /> {kinds[k]}</label>)}
          </fieldset>
          {hostedPreset && <div className="inline-note" aria-label={hostedPreset.label}>
            {form.connection_type==="nvidia"&&<p className="nvidia-tool-heading"><NvidiaLogo />Hosted API · Nemotron</p>}
            <p>{hostedPreset.description}</p>
            <p>Enter this provider’s key, find the models it offers, then save and select this connection as the Planner LLM or Task LLM.</p>
            <div className="section-toolbar"><a href={hostedPreset.url} target="_blank" rel="noreferrer">{hostedPreset.link}</a><button type="button" disabled={locked} onClick={()=>download(hostedPreset.file,hostedPreset.code,"text/x-python")}>Download adapter function</button><button className="text-button expert-only" type="button" disabled={locked} onClick={()=>setKind("custom")}>Customize adapter function</button></div>
          </div>}
          {form.connection_type === "custom" && !expert && <p className="inline-note">This profile uses custom Python code. Switch to Expert mode to edit it; it can still be selected and tested here.</p>}
          <label className="field">Name<input aria-label="LLM name" required value={form.name} disabled={locked} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label className="field">{form.connection_type === "ollama" ? "Ollama address on the RoboDE server" : "API address"}<input aria-label="LLM base_url" required value={form.base_url} disabled={locked} onChange={(e) => {
            setKey(""); if(selectedProfile?.has_api_key)setClearKey(true);
            setForm({ ...form, base_url: e.target.value });
          }} /></label>
          {(form.connection_type === "openai"||hostedPreset) && <>
            <label className="field">API key · stored on the server only<input aria-label="LLM API key" type="password" autoComplete="new-password" value={key} disabled={locked}
              placeholder={selectedProfile?.has_api_key ? "Saved key · leave blank to keep" : "Stored with owner-only file permissions"} onChange={(e) => setKey(e.target.value)} /></label>
            {edit && <label className="check-row"><input type="checkbox" checked={clearKey} disabled={locked} onChange={(e) => setClearKey(e.target.checked)} />Clear stored key</label>}
          </>}
          <label className="field">Model
            <input aria-label="LLM model" list="discovered-models" required value={form.model} disabled={locked} placeholder="Choose a discovered model or type its exact name" onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </label>
          <datalist id="discovered-models">{found?.map((m) => <option key={m} value={m} />)}</datalist>
          {form.connection_type !== "custom" && <div className="section-toolbar">
            <button type="button" disabled={locked || !form.base_url} onClick={() => void work(async () => {
              const result = await post<{ models: string[] }>("/llm/discover", { connection_type: form.connection_type, base_url: form.base_url, api_key: key || null, adapter_id: edit,api_key_env:form.api_key_env });
              setFound(result.models);
              setNotice(result.models.length ? `Found ${result.models.length} model${result.models.length === 1 ? "" : "s"}. Nothing was downloaded or started.` : "Connected, but this backend lists no models. Type the model name manually.");
            })}><RefreshCw size={13} /> {hostedPreset?"Check key & find models":"Test connection & find models"}</button>
          </div>}
          {found && !!found.length && <ul className="readiness" aria-label="Discovered models">{found.map((m) => <li key={m} className={m === form.model ? "ok" : ""}><button type="button" className="text-button" disabled={locked} onClick={() => setForm({ ...form, model: m })}>{m}</button>{isNemotron(m) && <span className="nemotron-tag">NVIDIA Nemotron</span>}</li>)}</ul>}
          <details className="expert-only"><summary>Advanced connection settings</summary>
            <label className="field">API key environment variable · optional<input aria-label="LLM api_key_env" value={form.api_key_env} disabled={locked} onChange={(e) => setForm({ ...form, api_key_env: e.target.value })} /></label>
            <label className="check-field"><input type="checkbox" checked={form.structured_outputs} disabled={locked} onChange={(e) => setForm({ ...form, structured_outputs: e.target.checked })} />Provider supports JSON outputs (including local Ollama)</label>
            <label className="check-field"><input type="checkbox" checked={form.supports_vision} disabled={locked} onChange={(e) => setForm({ ...form, supports_vision: e.target.checked })} />Vision-capable model (custom functions require invoke_multimodal)</label>
            <div className="configuration-grid">{(["timeout_seconds", "max_tokens"] as const).map((k) => <label className="field" key={k}>{k === "max_tokens" ? "Maximum output tokens" : "Timeout · seconds"}
              <input aria-label={`LLM ${k}`} type="number" min="1" max={k === "max_tokens" ? 16384 : 300} value={form[k]} disabled={locked} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} /></label>)}</div>
          </details>
          {form.connection_type === "custom" && <section className="llm-code-setup expert-only">
            <h4>Standard function</h4>
            <p>Define <code>async def invoke(input: str, system_prompt: str) -&gt; str</code>. Forward the supplied instructions to your provider and return its answer text.</p>
            <div className="section-toolbar">
              <button type="button" disabled={locked} onClick={() => setForm({ ...form, source_code: sampleCode })}>Load sample code</button>
              <button type="button" onClick={() => download("ollama_adapter.py", sampleCode, "text/x-python")}>Download sample</button>
              <label className="text-button">Import .py<input type="file" accept=".py" aria-label="Import LLM adapter code" disabled={locked} onChange={(e) => { const file = e.target.files?.[0]; if (file) void work(async () => {
                if (file.size > 60000) throw new Error("Code must be at most 60 KB"); setForm({ ...form, source_code: await file.text() }); }); e.target.value = ""; }} /></label>
            </div>
            <div role="group" aria-label="Python LLM adapter editor"><Suspense fallback={<p>Loading code editor…</p>}><AdapterCodeEditor value={form.source_code} disabled={locked} onChange={(source_code) => setForm({ ...form, source_code })} /></Suspense></div>
            <p className="inline-note">Custom code runs in a separate worker on the server with a timeout. Use code you trust; it can access server files and the network.</p>
          </section>}
          <div className="section-toolbar">
            <button className="primary" type="submit" disabled={locked}><Save size={14} /> Save AI model</button>
            {edit && <button type="button" disabled={locked || providers.default_id === edit} onClick={() => void work(async () => {
              await api("/llm/default", { method: "PUT", body: JSON.stringify({ adapter_id: edit }) }); await onSaved(); setNotice("Workspace default updated. Recompile affected plans.");
            })}><Star size={13} /> Set default</button>}
            {edit && <button type="button" className="danger" disabled={locked} onClick={() => void work(async () => {
              await api(`/llm/adapters/${edit}`, { method: "DELETE" }); await onSaved(); setEdit(null); setForm(fresh); setNotice("AI model removed. Tasks that used it must select another model.");
            })}><Trash2 size={14} /> Delete</button>}
          </div>
          {edit && <section className="llm-test config-card">
            <h4>Test model</h4>
            <label className="field">Input<textarea aria-label="LLM test input" value={input} onChange={(e) => setInput(e.target.value)} /></label>
            <button type="button" className="secondary" disabled={locked || !input.trim()} onClick={() => void work(async () => {
              setAnswer(""); const result = await post<{ answer: string; model: string; duration_seconds: number }>(`/llm/adapters/${edit}/invoke`, { input });
              setAnswer(result.answer); setNotice(`${result.model} answered in ${result.duration_seconds.toFixed(1)} s.`);
            })}><Play size={13} />{busy ? "Waiting…" : "Test model"}</button>
            {answer && <pre className="llm-answer" aria-label="LLM test answer">{answer}</pre>}
            <small>Uses the saved profile and contacts its connection from the backend.</small>
          </section>}
        </form>
      </div>

    </section>
  );
}

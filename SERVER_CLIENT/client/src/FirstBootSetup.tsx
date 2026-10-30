import { useState } from "react";
import { Check, Copy, RefreshCw } from "lucide-react";
import { api, post } from "./api";
import { isNemotron } from "./AIModels";
import Feedback from "./ui/Feedback";
import NvidiaLogo from "./branding/NvidiaLogo";

export type SetupInfo = { edition: "standard" | "nvidia"; completed: boolean; defaults: { simulator: string; compute: string; ai: string }; saved: Record<string, unknown> | null };
type Simulator = "isaac_sim" | "builtin";
type Compute = "nebius" | "gcp" | "local" | "remote";
type AI = "token_factory" | "ollama" | "existing" | "skip";
const steps = ["Simulator", "Compute", "AI model", "Review"];
const computeLabels: Record<Compute, [string, string]> = {
  nebius: ["Nebius GPU VM", "Isaac Sim runs on a GPU VM you start in the Nebius console. RoboDE connects over SSH."],
  gcp: ["Google Cloud GPU VM", "Use your existing GCP VM. RoboDE can start and stop it."],
  local: ["This machine", "Isaac Sim on a local NVIDIA RTX GPU (Linux or Windows)."],
  remote: ["Other Isaac worker", "Any reachable Isaac worker, for example through your own SSH tunnel."],
};
const aiLabels: Record<AI, [string, string]> = {
  token_factory: ["NVIDIA Nemotron on Nebius Token Factory", "Hosted inference. Needs a Token Factory API key; no VM."],
  ollama: ["Ollama on the RoboDE server", "Local models such as Nemotron through Ollama."],
  existing: ["Keep current AI models", "Use whatever is already configured in AI Models."],
  skip: ["Set up later", "Add an AI model later in Configuration → AI Models."],
};

/** First-boot setup. Saved per edition; can be reopened later from Runtime & integrations. */
export default function FirstBootSetup({ info, onDone, onClose }: { info: SetupInfo; onDone: (next: SetupInfo) => void; onClose?: () => void }) {
  const saved = info.saved ?? {};
  const nvidia = info.edition === "nvidia";
  const [step, setStep] = useState(0);
  const [simulator, setSimulator] = useState<Simulator>((saved.simulator as Simulator) ?? (info.defaults.simulator as Simulator));
  const [compute, setCompute] = useState<Compute>((saved.compute as Compute) ?? (info.defaults.compute as Compute));
  const [host, setHost] = useState(String(saved.nebius_host ?? "")), [user, setUser] = useState(String(saved.nebius_ssh_user ?? "ubuntu")), [keyFile, setKeyFile] = useState(String(saved.ssh_key_file ?? ""));
  const [token, setToken] = useState(""), [copied, setCopied] = useState(false);
  const [ai, setAI] = useState<AI>((saved.ai as AI) ?? (info.defaults.ai as AI));
  const [apiKey, setApiKey] = useState(""), [model, setModel] = useState(String(saved.ai_model ?? "")), [taskModel, setTaskModel] = useState(String(saved.ai_task_model ?? "")), [ollama, setOllama] = useState(String(saved.ollama_url ?? "http://localhost:11434/v1"));
  const [models, setModels] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const work = async (fn: () => Promise<void>) => { setBusy(true); setError(""); setNotice(""); try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const order = (list: string[]) => [...list.filter(isNemotron), ...list.filter((m) => !isNemotron(m))];
  const isaac = simulator === "isaac_sim";
  const blocked = step === 1 && isaac && compute === "nebius" && !host.trim() ? "Enter the Nebius VM's public IP address or hostname."
    : step === 2 && (ai === "token_factory" || ai === "ollama") && !model.trim() ? "Choose a model, or pick “Set up later”."
    : step === 2 && ai === "token_factory" && !apiKey.trim() ? "Enter your Token Factory API key, or pick “Set up later”." : "";
  const save = () => work(async () => {
    const next = await api<SetupInfo>("/setup", { method: "PUT", body: JSON.stringify({ simulator, compute, nebius_host: host, nebius_ssh_user: user, ssh_key_file: keyFile,
      worker_token: token || null, ai, ai_model: model, ai_task_model: taskModel, ai_api_key: apiKey || null, ollama_url: ollama }) });
    onDone(next);
  });
  const choice = <T extends string>(labels: Record<T, [string, string]>, value: T, set: (v: T) => void, group: string) =>
    <div className="choice-grid" role="group" aria-label={group}>{(Object.keys(labels) as T[]).map((k) =>
      <button key={k} type="button" aria-pressed={value === k} disabled={busy} onClick={() => set(k)}><strong>{labels[k][0]}{info.defaults[group === "AI model" ? "ai" : "compute"] === k && " · recommended"}</strong><small>{labels[k][1]}</small></button>)}</div>;
  return (
    <div className="modal-backdrop">
      <div className="modal first-boot" role="dialog" aria-modal="true" aria-label="First-boot setup">
        <div className="section-toolbar"><div><span className="eyebrow">{nvidia ? "ROBODE FOR NVIDIA" : "ROBODE"} · SETUP</span><h2>{nvidia ? <><NvidiaLogo /> Set up RoboDE for NVIDIA</> : "Set up RoboDE"}</h2></div>
          {onClose && <button aria-label="Close setup" disabled={busy} onClick={onClose}>Close</button>}</div>
        <p>Choose where simulation and AI run. Everything can be changed later; existing projects and robots are kept.</p>
        <ol className="setup-progress">{steps.map((s, i) => <li key={s} className={i === step ? "active" : ""}>{i + 1}. {s}</li>)}</ol>
        <Feedback message={error} />{notice && <p className="inline-note" role="status">{notice}</p>}
        {step === 0 && <><h3>Simulator</h3><div className="choice-grid" role="group" aria-label="Simulator">
          <button type="button" aria-pressed={isaac} onClick={() => setSimulator("isaac_sim")}><strong><NvidiaLogo /> NVIDIA Isaac Sim{info.defaults.simulator === "isaac_sim" && " · recommended"}</strong><small>Physics, sensors and native rendering on an NVIDIA RTX GPU.</small></button>
          <button type="button" aria-pressed={!isaac} onClick={() => setSimulator("builtin")}><strong>Built-in simulator{info.defaults.simulator === "builtin" && " · recommended"}</strong><small>Kinematic preview on this computer. No GPU needed.</small></button></div>
          <small>New projects use this simulator. Existing projects keep theirs; switch one in its Environment workspace.</small></>}
        {step === 1 && (!isaac ? <p>The built-in simulator runs on the RoboDE server; there is nothing to configure.</p> : <><h3>Where Isaac Sim runs</h3>{choice(computeLabels, compute, setCompute, "Compute")}
          {compute === "nebius" && <div className="config-card">
            <p>Create and start an NVIDIA RTX GPU VM (for example L40S) in the Nebius console and install the RoboDE Isaac worker on it. RoboDE never starts, stops or creates the VM; its idle watchdog powers it off.</p>
            <div className="configuration-grid">
              <label className="field">VM public IP or hostname<input aria-label="Nebius VM address" value={host} placeholder="203.0.113.10" onChange={(e) => setHost(e.target.value)} /></label>
              <label className="field">SSH user<input aria-label="Nebius SSH user" value={user} onChange={(e) => setUser(e.target.value)} /></label></div>
            <label className="field">SSH private key on the RoboDE server · optional<input aria-label="Nebius SSH key file" value={keyFile} placeholder="/Users/you/.ssh/id_ed25519" onChange={(e) => setKeyFile(e.target.value)} /></label>
            <div className="section-toolbar"><button type="button" disabled={busy} onClick={() => work(async () => { const r = await post<{ token: string }>("/configuration/isaac/token"); setToken(r.token); setCopied(false); })}><RefreshCw size={13} /> Generate worker token</button>
              {token && <button type="button" onClick={() => { void navigator.clipboard?.writeText(token).then(() => setCopied(true)); }}>{copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy token"}</button>}</div>
            {token ? <small>Set this as ISAAC_WORKER_TOKEN on the VM's worker. It is saved on this server when you finish setup and is not shown again.</small> : <small>Leave empty to keep the current worker token, or generate one for a new VM.</small>}
          </div>}
          {compute !== "nebius" && <small>Finish the {computeLabels[compute][0]} details in Runtime & integrations after setup.</small>}</>)}
        {step === 2 && <><h3>AI model for planning</h3>{choice(aiLabels, ai, (v) => { setAI(v); setModels(null); setModel(""); }, "AI model")}
          {ai === "token_factory" && <div className="config-card">
            <p>Create a key in Nebius Token Factory → API keys. It is stored only on the RoboDE server.</p>
            <label className="field">Token Factory API key<input aria-label="Token Factory API key" type="password" autoComplete="new-password" value={apiKey} onChange={(e) => { setApiKey(e.target.value); setModels(null); }} /></label>
            <button type="button" disabled={busy || !apiKey.trim()} onClick={() => work(async () => { const r = await post<{ models: string[] }>("/llm/discover", { connection_type: "nebius", base_url: "https://api.tokenfactory.nebius.com/v1", api_key: apiKey }); setModels(order(r.models)); if (!model) setModel(r.models.find(isNemotron) ?? ""); setNotice(`Key accepted. ${r.models.filter(isNemotron).length} Nemotron models available.`); })}><RefreshCw size={13} /> Check key & find Nemotron models</button>
          </div>}
          {ai === "ollama" && <div className="config-card"><label className="field">Ollama address on the RoboDE server<input aria-label="Ollama address" value={ollama} onChange={(e) => setOllama(e.target.value)} /></label>
            <button type="button" disabled={busy} onClick={() => work(async () => { const r = await post<{ models: string[] }>("/llm/discover", { connection_type: "ollama", base_url: ollama }); setModels(order(r.models)); })}><RefreshCw size={13} /> Find installed models</button></div>}
          {(ai === "token_factory" || ai === "ollama") && <label className="field">Planner LLM model<input aria-label="Setup AI model" list="setup-models" value={model} placeholder="Choose a found model or type its exact ID" onChange={(e) => setModel(e.target.value)} /><datalist id="setup-models">{models?.map((m) => <option key={m} value={m} />)}</datalist></label>}
          {(ai === "token_factory" || ai === "ollama") && <label className="field">Task LLM model · optional<input aria-label="Setup Task LLM model" list="setup-models" value={taskModel} placeholder="Leave empty to use the same model for tasks" onChange={(e) => setTaskModel(e.target.value)} /></label>}
          {(ai === "token_factory" || ai === "ollama") && <small>The model above is the Planner LLM. A separate Task LLM converts each task into robot actions, for example a larger planner with a faster task model.</small>}
          {models && <ul className="readiness" aria-label="Available models">{models.slice(0, 24).map((m) => <li key={m} className={m === model ? "ok" : ""}><button type="button" className="text-button" onClick={() => setModel(m)}>{m}</button>{isNemotron(m) && <span className="nemotron-tag">NVIDIA Nemotron</span>}</li>)}</ul>}
          {(ai === "token_factory" || ai === "ollama") && <small>This becomes the workspace default AI model, shared with the standard RoboDE build.</small>}</>}
        {step === 3 && <><h3>Review</h3><ul>
          <li>Simulator: <strong>{isaac ? "NVIDIA Isaac Sim" : "Built-in simulator"}</strong> for new projects</li>
          {isaac && <li>Isaac Sim runs on: <strong>{computeLabels[compute][0]}</strong>{compute === "nebius" && ` · ${user}@${host}`}{token && " · new worker token"}</li>}
          <li>Planner LLM: <strong>{ai === "token_factory" || ai === "ollama" ? `${model} (${aiLabels[ai][0]})` : aiLabels[ai][0]}</strong></li>
          {(ai === "token_factory" || ai === "ollama") && <li>Task LLM: <strong>{taskModel.trim() || model}</strong></li>}</ul>
          {nvidia && <small>This build keeps its own simulator connection, so your standard RoboDE GCP or local setup is unchanged.</small>}</>}
        {blocked && <p className="field-issue" role="note">{blocked}</p>}
        <div className="section-toolbar">
          <button type="button" disabled={busy || step === 0} onClick={() => setStep(step - 1)}>Back</button>
          {step < 3 ? <button className="primary" type="button" disabled={busy || !!blocked} onClick={() => setStep(step + 1)}>Continue · {steps[step + 1]}</button>
            : <button className="primary" type="button" disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Save setup"}</button>}
        </div>
      </div>
    </div>
  );
}

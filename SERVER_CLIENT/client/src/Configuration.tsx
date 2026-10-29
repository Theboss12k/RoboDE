import Feedback from "./ui/Feedback";
import { lazy, Suspense, useEffect, useState } from "react";
import { Plus, Save, Trash2, X, Play } from "lucide-react";
import { api, post, download } from "./api";
import sampleCode from "../../server/examples/llm/ollama_adapter.py?raw";
import type {
  LLMAdapter,
  LLMConfiguration,
  ProjectDetail,
} from "./types";
import GlobalRobotLibrary from "./GlobalRobotLibrary";
import WorkspaceAccess from "./WorkspaceAccess";
const AdapterCodeEditor = lazy(() => import("./CodeView").then((m) => ({ default: m.AdapterCodeEditor })));
const fresh = {
  name: "",
  protocol: "chat_completions" as LLMAdapter["protocol"],
  base_url: "http://localhost:11434/v1",
  model: "",
  source_code: sampleCode,
  timeout_seconds: 60,
  max_tokens: 2048,
  api_key_env: "",
};
export default function Configuration({
  initialTab = "robots",
  disabled,
  onClose,
  onChanged,
}: {
  initialTab?: "robots" | "llm";
  detail: ProjectDetail | null;
  disabled: boolean;
  onClose: () => void;
  onChanged: () => void;
  onAdded: () => void;
}) {
  const [tab, setTab] = useState<"robots" | "llm" | "access">("robots"),
    [providers, setProviders] = useState<LLMConfiguration>({
      adapters: [],
      default_id: null,
    });
  const [edit, setEdit] = useState<string | null>(null),
    [form, setForm] = useState(fresh),
    [key, setKey] = useState(""),
    [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [input, setInput] = useState("Reply with a short greeting."),
    [answer, setAnswer] = useState("");
  useEffect(() => setTab(initialTab), [initialTab]);
  const load = async () => {
    const p = await api<LLMConfiguration>("/llm/adapters");
    setProviders(p);
  };
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const select = (p: LLMAdapter) => {
    setEdit(p.id);
    setForm({ ...fresh, ...p, source_code: p.source_code || sampleCode });
    setKey("");
    setClearKey(false);
    setAnswer("");
  };
  const locked = busy || disabled;
  return (
    <div
      className="modal configuration-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Global configuration"
    >
      <div className="section-toolbar">
        <div>
          <span className="eyebrow">GLOBAL CONFIGURATION</span>
          <h2>Global robots & adapters</h2>
        </div>
        <button
          aria-label="Close configuration"
          disabled={busy}
          onClick={onClose}
        >
          <X size={17} />
        </button>
      </div>
      <nav className="view-tabs" aria-label="Configuration sections">
        {(["robots", "llm", "access"] as const).map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            disabled={busy}
            onClick={() => setTab(t)}
          >
            {t === "robots" ? "Robot library" : t === "llm" ? "LLM adapters" : "Workspace access"}
          </button>
        ))}
      </nav>
      <Feedback message={error} />
      {notice && (
        <p role="status" className="inline-note">
          {notice}
        </p>
      )}
      {tab === "access" ? <WorkspaceAccess/> : tab === "robots" ? (
        <GlobalRobotLibrary disabled={locked} onChanged={onChanged} onBusyChange={setBusy}/>
      ) : (
        <div className="llm-configuration">
          <aside>
            <div className="section-toolbar">
              <h3>Adapters</h3>
              <button
                aria-label="New LLM adapter"
                disabled={locked}
                onClick={() => {
                  setEdit(null);
                  setForm(fresh);
                  setKey("");
                  setClearKey(false);
                  setAnswer("");
                }}
              >
                <Plus size={15} />
              </button>
            </div>
            {providers.adapters.map((p) => (
              <button
                className={edit === p.id ? "selected" : ""}
                disabled={busy}
                key={p.id}
                onClick={() => select(p)}
              >
                <strong>{p.name}</strong>
                <small>
                  {p.model}
                  {providers.default_id === p.id ? " · default" : ""}
                </small>
              </button>
            ))}
            <label className="field">
              Global default
              <select
                aria-label="Default LLM adapter"
                value={providers.default_id ?? ""}
                disabled={locked}
                onChange={(e) =>
                  void work(async () => {
                    await api("/llm/default", {
                      method: "PUT",
                      body: JSON.stringify({
                        adapter_id: e.target.value || null,
                      }),
                    });
                    await load();
                    onChanged();
                    setNotice(
                      "Default adapter updated. Recompile affected plans.",
                    );
                  })
                }
              >
                <option value="">Local templates for robot drafting</option>
                {providers.adapters.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <p>
              Choose a different adapter in any task. Standalone LLM tasks
              require a configured adapter.
            </p>
          </aside>
          <div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void work(async () => {
                  const value = {
                    ...fresh,
                    ...Object.fromEntries(
                      Object.keys(fresh).map((k) => [
                        k,
                        form[k as keyof typeof fresh],
                      ]),
                    ),
                    source_code: form.protocol === "python_function" ? form.source_code : "",
                    api_key: key || null,
                    clear_api_key: clearKey,
                  };
                  const p = edit
                    ? await api<LLMAdapter>(`/llm/adapters/${edit}`, {
                        method: "PUT",
                        body: JSON.stringify(value),
                      })
                    : await post<LLMAdapter>("/llm/adapters", value);
                  await load();
                  select(p);
                  onChanged();
                  setNotice("LLM adapter saved. Recompile affected plans.");
                });
              }}
            >
              <h3>{edit ? "Edit adapter" : "Add LLM adapter"}</h3>
              <p>
                Connect your provider using the form, or paste a Python function.
                The IDE supplies its instructions internally for planning and adapter generation.
              </p>
              <fieldset className="llm-setup-choice" disabled={locked}>
                <legend>Setup method</legend>
                <label><input type="radio" name="llm-setup" checked={form.protocol === "chat_completions"}
                  onChange={() => setForm({ ...form, protocol: "chat_completions" })} /> Configure with UI</label>
                <label><input type="radio" name="llm-setup" checked={form.protocol === "python_function"}
                  onChange={() => setForm({ ...form, protocol: "python_function" })} /> Paste adapter code</label>
              </fieldset>
              {(["name", "base_url", "model", "api_key_env"] as const).map(
                (k) => (
                  <label className="field" key={k}>
                    {
                      {
                        name: "Adapter name",
                        base_url: "API base URL",
                        model: "Model",
                        api_key_env: "API key environment variable · optional",
                      }[k]
                    }
                    <input
                      aria-label={`LLM ${k}`}
                      value={form[k]}
                      required={k !== "api_key_env"}
                      disabled={locked}
                      onChange={(e) =>
                        setForm({ ...form, [k]: e.target.value })
                      }
                    />
                  </label>
                ),
              )}
              <label className="field">
                API key · optional
                <input
                  aria-label="LLM API key"
                  type="password"
                  autoComplete="new-password"
                  value={key}
                  disabled={locked}
                  placeholder={
                    providers.adapters.find((p) => p.id === edit)?.has_api_key
                      ? "Saved key · leave blank to keep"
                      : "Stored locally with owner-only file permissions"
                  }
                  onChange={(e) => setKey(e.target.value)}
                />
              </label>
              {edit && (
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={clearKey}
                    disabled={locked}
                    onChange={(e) => setClearKey(e.target.checked)}
                  />
                  Clear stored key
                </label>
              )}
              {form.protocol === "python_function" && <section className="llm-code-setup">
                <h4>Standard adapter function</h4>
                <p>Define <code>async def invoke(input: str, system_prompt: str) -&gt; str</code>.
                  Forward the supplied instructions to your provider and return its answer text.</p>
                <div className="section-toolbar">
                  <button type="button" disabled={locked} onClick={() => setForm({ ...form, source_code: sampleCode })}>Load sample code</button>
                  <button type="button" onClick={() => download("ollama_adapter.py", sampleCode, "text/x-python")}>Download sample</button>
                  <label className="text-button">Import .py<input type="file" accept=".py" aria-label="Import LLM adapter code" disabled={locked}
                    onChange={(e) => { const file = e.target.files?.[0]; if (file) void work(async () => {
                      if (file.size > 60000) throw new Error("Adapter code must be at most 60 KB");
                      setForm({ ...form, source_code: await file.text() });
                    }); e.target.value = ""; }} /></label>
                </div>
                <div role="group" aria-label="Python LLM adapter editor">
                  <Suspense fallback={<p>Loading code editor…</p>}><AdapterCodeEditor value={form.source_code} disabled={locked}
                    onChange={(source_code) => setForm({ ...form, source_code })} /></Suspense>
                </div>
                <p className="inline-note">Custom code runs in a separate worker on the server with a timeout. Use code you trust; it can access server files and the network. Connection values are passed through ROBOT_IDE_LLM_* environment variables.</p>
              </section>}
              <div className="configuration-grid">
                {(["timeout_seconds", "max_tokens"] as const).map((k) => (
                  <label className="field" key={k}>
                    {k === "max_tokens"
                      ? "Maximum output tokens"
                      : "Timeout · seconds"}
                    <input
                      aria-label={`LLM ${k}`}
                      type="number"
                      min="1"
                      max={k === "max_tokens" ? 16384 : 300}
                      value={form[k]}
                      disabled={locked}
                      onChange={(e) =>
                        setForm({ ...form, [k]: Number(e.target.value) })
                      }
                    />
                  </label>
                ))}
              </div>
              <div className="section-toolbar">
                <button className="primary" type="submit" disabled={locked}>
                  <Save size={14} /> Save LLM adapter
                </button>
                {edit && (
                  <button
                    type="button"
                    className="danger"
                    disabled={locked}
                    onClick={() =>
                      void work(async () => {
                        await api(`/llm/adapters/${edit}`, {
                          method: "DELETE",
                        });
                        await load();
                        setEdit(null);
                        setForm(fresh);
                        setKey("");
                        onChanged();
                        setNotice(
                          "Adapter removed. Tasks referencing it must select another adapter.",
                        );
                      })
                    }
                  >
                    <Trash2 size={14} /> Delete
                  </button>
                )}
              </div>
            </form>
            {edit && (
              <section className="llm-test config-card">
                <h3>Test the function</h3>
                <label className="field">
                  Input
                  <textarea
                    aria-label="LLM test input"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                  />
                </label>
                <button
                  className="secondary"
                  disabled={locked || !input.trim()}
                  onClick={() =>
                    void work(async () => {
                      setAnswer("");
                      const result = await post<{ answer: string }>(
                        `/llm/adapters/${edit}/invoke`,
                        { input },
                      );
                      setAnswer(result.answer);
                    })
                  }
                >
                  <Play size={13} />
                  {busy ? "Waiting…" : "Invoke saved adapter"}
                </button>
                {answer && (
                  <pre className="llm-answer" aria-label="LLM test answer">
                    {answer}
                  </pre>
                )}
                <small>
                  Test calls use the saved configuration and contact the
                  selected provider.
                </small>
              </section>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

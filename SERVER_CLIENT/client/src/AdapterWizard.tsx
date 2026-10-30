import Feedback from "./ui/Feedback";
import NvidiaLogo from "./branding/NvidiaLogo";
import { useEffect, useState, useRef } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  Sparkles,
  X,
} from "lucide-react";
import type {
  AdapterBundle,
  AdapterCommand,
  CellRobot,
  LLMConfiguration,
  ProjectDetail,
} from "./types";
import { api, post, download } from "./api";
import AdapterControls from "./AdapterControls";
import IsaacRobotGuide from "./IsaacRobotGuide";
import CommandEditor, { waveExample } from "./CommandEditor";
const stages = [
  "Select target",
  "Choose method",
  "Configure commands",
  "Generate",
  "Review commands & adapter",
  "Simulator test",
];
export default function AdapterWizard({
  detail,
  robot,
  onClose,
  onGenerated,
  previewStage,
  globalModelId,
}: {
  detail: ProjectDetail;
  robot: CellRobot;
  onClose: () => void;
  onGenerated: (b: AdapterBundle) => void;
  previewStage?: number;
  globalModelId?: string;
}) {
  const [stage, setStage] = useState(0),
    [target, setTarget] = useState<"physical" | "virtual">("physical");
  const [method, setMethod] = useState<"documentation" | "custom">(
      "documentation",
    ),
    [kind, setKind] = useState<AdapterBundle["kind"]>("sdk");
  const [name, setName] = useState("Robot adapter"),
    [version, setVersion] = useState(""),
    [docs, setDocs] = useState("");
  const [commands, setCommands] = useState<AdapterCommand[]>([]),
    [llm, setLLM] = useState<LLMConfiguration>({
      adapters: [],
      default_id: null,
    }),
    [provider, setProvider] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.keys(robot.model.actuators.actuators).map((k) => [k, k]),
    ),
  );
  const [units, setUnits] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(robot.model.actuators.actuators).map(([k, a]) => [
        k,
        a.unit,
      ]),
    ),
  );
  const [bridge, setBridge] = useState("http://127.0.0.1:8767"),
    [tokenEnv, setTokenEnv] = useState("ROS_BRIDGE_TOKEN");
  const [bundle, setBundle] = useState<AdapterBundle | null>(null),
    [reviewed, setReviewed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [controlActive, setControlActive] = useState(false);
  const controlSession = useRef<string|null>(null);
  const visibleStage = previewStage ?? stage;
  useEffect(() => {
    void api<LLMConfiguration>("/llm/adapters")
      .then(setLLM)
      .catch((e) => setError(e.message));
  }, []);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const closeWizard = () => work(async()=>{
    const sid=controlSession.current;
    if(sid){await api(`/controls/${sid}`,{method:'DELETE'});controlSession.current=null;setControlActive(false);}
    onClose();
  });
  const payload = () => ({
    model_id: robot.model.robot.id,
    name,
    target,
    kind,
    configuration_method: method,
    sdk_version: version,
    documentation: docs,
    commands: commands.length ? commands : undefined,
    llm_adapter_id: provider || null,
    joint_mapping: mapping,
    remote_units: target === "physical" && kind === "sdk" ? units : {},
    connection:
      kind === "ros2" ? { bridge_url: bridge, token_env: tokenEnv } : {},
  });
  const chooseMethod = (next: typeof method) => {
    setMethod(next);
    setCommands(
      next === "custom"
        ? robot.model.actuators.actuators.base_yaw
          ? [waveExample()]
          : [
              {
                id: "read_feedback",
                name: "Read feedback",
                description: "Read the simulated joint state.",
                vendor_command: "",
                parameters: {},
                steps: [{ operation: "feedback", values: {}, duration: 0.5 }],
                simulation_supported: true,
                unsupported_reason: "",
              },
            ]
        : [],
    );
  };
  return (
    <section
      className={`adapter-wizard ${visibleStage === 5 ? "command-test-window" : ""} ${previewStage !== undefined ? "tutorial-preview" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label="Adapter setup wizard"
    >
      <div className="section-toolbar">
        <div>
          <span className="eyebrow">
            ROBOT SETUP / {robot.instance.instance.name}
          </span>
          <h2>Configure the target. Review and test its commands.</h2>
        </div>
        <button
          aria-label="Close adapter wizard"
          onClick={()=>void closeWizard()}
          disabled={busy}
        >
          <X size={18} />
        </button>
      </div>
      <ol className="wizard-stages">
        {stages.map((s, i) => (
          <li
            className={
              i === visibleStage ? "active" : i < visibleStage ? "complete" : ""
            }
            key={s}
          >
            <span>{i < visibleStage ? <Check size={11} /> : i + 1}</span>
            {s}
          </li>
        ))}
      </ol>
      <Feedback message={error} />
      <div className="wizard-body">
        {visibleStage === 0 ? (
          <>
            <h3>Where will this adapter be used?</h3>
            <div className="adapter-choices">
              {(["physical", "virtual"] as const).map((t) => (
                <button
                  key={t}
                  className={target === t ? "selected" : ""}
                  aria-pressed={target === t}
                  onClick={() => {
                    setTarget(t);
                    setKind(t === "physical" ? "sdk" : "mock");
                  }}
                >
                  <span className="tiny-tag">Target</span>
                  <strong>
                    {t === "physical" ? "Physical robot" : "Virtual robot"}
                  </strong>
                  <p>
                    {t === "physical"
                      ? "Configure a real device interface. Initial tests always use the built-in simulator."
                      : "Configure the built-in simulator or an Isaac Sim environment."}
                  </p>
                </button>
              ))}
            </div>
            <div className="wizard-model-summary">
              <strong>{robot.model.robot.name}</strong>
              <span>
                Registered model {robot.model.robot.id} ·{" "}
                {robot.model.robot.version}
              </span>
              <small>
                Joint names, units and limits come from this model. Add/import
                models in Configuration → Robot library.
              </small>
            </div>
          </>
        ) : visibleStage === 1 ? (
          <>
            <h3>How would you like to configure commands?</h3>
            <div className="adapter-choices">
              <button
                className={method === "documentation" ? "selected" : ""}
                aria-pressed={method === "documentation"}
                onClick={() => chooseMethod("documentation")}
              >
                <span className="tiny-tag">Vendor documentation</span>
                <strong>Use vendor documentation</strong>
                <p>
                  Provide SDK/API documentation. Your selected LLM drafts a
                  command catalog and simulator recipes for review.
                </p>
              </button>
              <button
                className={method === "custom" ? "selected" : ""}
                aria-pressed={method === "custom"}
                onClick={() => chooseMethod("custom")}
              >
                <span className="tiny-tag">Custom tasks</span>
                <strong>Define custom commands</strong>
                <p>
                  Name a task, define parameters and combine joint moves,
                  gripper, wait, feedback and stop steps. Works offline.
                </p>
              </button>
            </div>
            <p>
              Target: {target}. Every resulting command lists its parameters,
              units and simulator support.
            </p>
          </>
        ) : visibleStage === 2 ? (
          <>
            <div className="configuration-grid">
              <label className="field">
                Adapter name
                <input
                  aria-label="Adapter name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="nvidia-tool-heading">
                  {target === "physical"
                    ? "Device interface"
                    : "Virtual environment"}
                  {kind === "isaac_sim" && <NvidiaLogo />}
                </span>
                <select
                  aria-label="Adapter interface"
                  value={kind}
                  onChange={(e) => setKind(e.target.value as typeof kind)}
                >
                  {target === "physical" ? (
                    <>
                      <option value="sdk">Vendor SDK</option>
                      <option value="ros2">ROS 2 bridge</option>
                    </>
                  ) : (
                    <>
                      <option value="mock">Built-in simulator</option>
                      <option value="isaac_sim">NVIDIA Isaac Sim</option>
                    </>
                  )}
                </select>
              </label>
            </div>
            {method === "documentation" && (
              <>
                <div className="configuration-grid">
                  <label className="field">
                    SDK/API version
                    <input
                      aria-label="SDK version"
                      value={version}
                      onChange={(e) => setVersion(e.target.value)}
                    />
                  </label>
                  <label className="field">
                    AI model
                    <select
                      aria-label="Documentation LLM adapter"
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                    >
                      <option value="">
                        Workspace default ·{" "}
                        {llm.adapters.find((p) => p.id === llm.default_id)
                          ?.name ?? "None configured"}
                      </option>
                      {llm.adapters.map((p) => (
                        <option value={p.id} key={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label className="field">
                  Vendor SDK/API documentation
                  <textarea
                    aria-label="SDK documentation"
                    rows={7}
                    value={docs}
                    placeholder="Paste command signatures and their documented meanings, parameters, units, feedback and stop behavior."
                    onChange={(e) => {
                      setDocs(e.target.value);
                      setCommands([]);
                    }}
                  />
                </label>
                <label className="file-import">
                  Import documentation text
                  <input
                    aria-label="Import SDK documentation"
                    type="file"
                    accept=".txt,.md,.py,.json"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        if (file.size > 60000) {
                          setError("Documentation must be at most 60 KB");
                          return;
                        }
                        void file
                          .text()
                          .then((text) => {
                            setDocs(text);
                            setCommands([]);
                          })
                          .catch((err) => setError(String(err)));
                      }
                    }}
                  />
                </label>
                <button
                  className="secondary"
                  disabled={
                    busy ||
                    !docs.trim() ||
                    !version.trim() ||
                    !(provider || llm.default_id) ||
                    previewStage !== undefined
                  }
                  onClick={() =>
                    void work(async () => {
                      const result = await post<{ commands: AdapterCommand[] }>(
                        globalModelId ? `/library/robots/${globalModelId}/adapters/discover-commands` : `/projects/${detail.project.id}/adapters/discover-commands`,
                        payload(),
                      );
                      setCommands(result.commands);
                    })
                  }
                >
                  <Sparkles size={13} />
                  {busy ? "Extracting…" : "Extract commands from documentation"}
                </button>
                <p className="inline-note">
                  Documentation is sent to the selected provider. Missing or
                  ambiguous simulator implementations are marked unavailable.
                  SDK transport source is a reviewable draft; simulator testing
                  does not validate real hardware.
                </p>
              </>
            )}
            {kind === "ros2" && (
              <div className="configuration-grid">
                <label className="field">
                  Bridge URL
                  <input
                    aria-label="ROS bridge URL"
                    value={bridge}
                    onChange={(e) => setBridge(e.target.value)}
                  />
                </label>
                <label className="field">
                  Token environment variable
                  <input
                    aria-label="ROS token environment variable"
                    value={tokenEnv}
                    onChange={(e) => setTokenEnv(e.target.value)}
                  />
                </label>
              </div>
            )}
            {(method === "custom" || commands.length > 0) && (
              <CommandEditor
                commands={commands}
                robot={robot}
                onChange={setCommands}
                disabled={busy}
              />
            )}
            <details className="adapter-mapping-details">
              <summary>Joint mapping & transport units</summary>
              <div className="mapping-table">
                {Object.entries(robot.model.actuators.actuators).map(
                  ([key, a]) => (
                    <div key={key}>
                      <span>
                        {key}
                        <small>
                          {a.unit} · {a.min}…{a.max}
                        </small>
                      </span>
                      <input
                        aria-label={`Remote joint ${key}`}
                        value={mapping[key]}
                        onChange={(e) =>
                          setMapping({ ...mapping, [key]: e.target.value })
                        }
                      />
                      <select
                        aria-label={`Remote unit ${key}`}
                        disabled={kind !== "sdk"}
                        value={kind === "sdk" ? units[key] : a.unit}
                        onChange={(e) =>
                          setUnits({ ...units, [key]: e.target.value })
                        }
                      >
                        {(a.unit === "rad" ? ["rad", "deg"] : ["m", "mm"]).map(
                          (u) => (
                            <option key={u}>{u}</option>
                          ),
                        )}
                      </select>
                    </div>
                  ),
                )}
              </div>
            </details>
            {kind === "isaac_sim" && <IsaacRobotGuide />}
          </>
        ) : visibleStage === 3 ? (
          <>
            <Sparkles size={30} />
            <h3>Generate the command catalog and adapter.</h3>
            <p>
              {target === "physical" ? "Physical" : "Virtual"} target ·{" "}
              {method === "custom"
                ? "Custom command recipes"
                : "Vendor documentation"}{" "}
              · {robot.model.robot.name}
            </p>
            <p>
              The bundle contains source, command definitions, joint mappings,
              simulator transport and contract tests. You will review the final
              command list before opening the test window.
            </p>
            <button
              className="primary"
              disabled={busy || previewStage !== undefined}
              onClick={() =>
                void work(async () => {
                  const generated = await post<AdapterBundle>(
                    globalModelId ? `/library/robots/${globalModelId}/adapters/generate` : `/projects/${detail.project.id}/adapters/generate`,
                    payload(),
                  );
                  setBundle(generated);
                  setReviewed(false);
                  onGenerated(generated);
                  if (!globalModelId && generated.category === "physical")
                    await post(
                      `/projects/${detail.project.id}/robots/${robot.instance.instance.id}/connections`,
                      {
                        name: `${generated.name} connection`,
                        adapter_id: generated.id,
                        connection: generated.connection,
                      },
                    );
                  setStage(4);
                })
              }
            >
              <Sparkles size={14} />
              {busy ? "Generating…" : "Generate draft"}
            </button>
          </>
        ) : visibleStage === 4 ? (
          <>
            <div className="section-toolbar">
              <h3 className="nvidia-tool-heading">
                {bundle?.kind === "isaac_sim" && <NvidiaLogo />}Available
                commands & final adapter
              </h3>
              {bundle && (
                <button
                  className="secondary"
                  onClick={() =>
                    download(
                      `adapter-${bundle.id}.json`,
                      JSON.stringify(bundle, null, 2),
                    )
                  }
                >
                  <Download size={13} /> Export bundle
                </button>
              )}
            </div>
            <p>
              Review every command’s meaning and simulator recipe, joint
              mappings and transport source. Unavailable commands cannot be
              tested until a simulator implementation is defined.
            </p>
            <div className="review-command-list">
              {bundle?.commands?.map((c) => (
                <details key={c.id}>
                  <summary>
                    <strong>{c.name}</strong>
                    <span className="tiny-tag">
                      {c.simulation_supported
                        ? "Simulator supported"
                        : "Unavailable"}
                    </span>
                  </summary>
                  <p>{c.description}</p>
                  {c.vendor_command && <code>{c.vendor_command}</code>}
                  <pre>
                    {JSON.stringify(
                      {
                        parameters: c.parameters,
                        steps: c.steps,
                        unsupported_reason: c.unsupported_reason || undefined,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              )) ?? <p>The final command list appears after generation.</p>}
            </div>
            <h3>Adapter source</h3>
            <pre className="adapter-source">
              {bundle?.adapter_code ??
                "# Generated adapter source appears here."}
            </pre>
            {bundle?.sdk_source && (
              <details>
                <summary>SDK transport draft · review only</summary>
                <pre className="adapter-source">{bundle.sdk_source}</pre>
              </details>
            )}
            <label className="review-check">
              <input
                type="checkbox"
                aria-label="I reviewed the generated adapter"
                checked={reviewed}
                onChange={(e) => setReviewed(e.target.checked)}
              />
              I reviewed the final commands, recipes, source and mappings.
            </label>
            <button
              className="primary"
              disabled={
                !reviewed || !bundle || busy || previewStage !== undefined
              }
              onClick={() =>
                void work(async () => {
                  const b = await post<AdapterBundle>(
                    `/adapters/${bundle!.id}/review`,
                    { expected_hash: bundle!.hash },
                  );
                  setBundle(b);
                  onGenerated(b);
                  const tested = await post<AdapterBundle>(
                    `/adapters/${b.id}/test`,
                  );
                  setBundle(tested);
                  onGenerated(tested);
                  setStage(5);
                })
              }
            >
              <Check size={14} />
              {busy
                ? "Validating transport…"
                : "Record review & open simulator"}
            </button>
          </>
        ) : bundle && previewStage === undefined ? (
          <>
            <div className="test-report">
              <strong>
                <Check size={14} /> Simulated contract tests passed
              </strong>
              <small>
                Test each available command below. Stop and Disconnect controls
                are available throughout.
              </small>
            </div>
            <AdapterControls
              detail={detail}
              robot={robot}
              adapter={bundle}
              onEnvironmentChanged={() => {}}
              onSessionChange={(active,sid)=>{setControlActive(active);controlSession.current=active?(sid??null):null}}
              globalModelId={globalModelId}
              testOnly
              autoConnect
            />
          </>
        ) : (
          <>
            <h3>Built-in command test window</h3>
            <p>
              After review and transport checks, the simulator opens
              automatically. Select a command, edit its parameters and run it.
              Feedback, translated commands, step progress and Stop confirmation
              appear here. This tutorial preview does not create a connection.
            </p>
          </>
        )}
      </div>
      <div className="wizard-footer">
        <button
          className="secondary"
          disabled={
            busy ||
            controlActive ||
            visibleStage === 0 ||
            previewStage !== undefined
          }
          onClick={() => setStage(stage - 1)}
        >
          <ArrowLeft size={13} /> Back
        </button>
        <small>
          {visibleStage + 1} / {stages.length}
        </small>
        {visibleStage < 3 ? (
          <button
            className="primary"
            disabled={
              busy ||
              previewStage !== undefined ||
              (visibleStage === 2 &&
                (!name.trim() ||
                  (method === "documentation" &&
                    (!version.trim() ||
                      !docs.trim() ||
                      !(provider || llm.default_id))) ||
                  (method === "custom" && !commands.length)))
            }
            onClick={() => setStage(stage + 1)}
          >
            Continue
            <ArrowRight size={13} />
          </button>
        ) : visibleStage === 5 ? (
          <button className="secondary" disabled={busy} onClick={()=>void closeWizard()}>
            Done
            <Check size={13} />
          </button>
        ) : (
          <span />
        )}
      </div>
    </section>
  );
}

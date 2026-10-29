import { useEffect, useState } from "react";
import { Plus, Download, Upload, ArrowLeft, ArrowRight } from "lucide-react";
import { api, post, download } from "./api";
import type { Model, ProjectDetail, AdapterBundle } from "./types";
import Feedback from "./ui/Feedback";
import AdapterWizard from "./AdapterWizard";
import AdapterControls from "./AdapterControls";
import URDFImport from "./URDFImport";

export default function GlobalRobotLibrary({
  disabled,
  onChanged,
  onBusyChange,
}: {
  disabled: boolean;
  onChanged: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [importMode, setImportMode] = useState<"json" | "urdf">("json");
  const [importKey, setImportKey] = useState(0);
  const [models, setModels] = useState<Model[]>([]),
    [all, setAll] = useState<AdapterBundle[]>([]),
    [section, setSection] = useState<"robots" | "adapters">("robots");
  const [step, setStep] = useState<number | null>(null),
    [selected, setSelected] = useState(""),
    [preview, setPreview] = useState<ProjectDetail | null>(null);
  const [json, setJSON] = useState(""),
    [id, setId] = useState(""),
    [name, setName] = useState(""),
    [target, setTarget] = useState<"physical" | "virtual">("virtual");
  const [adapter, setAdapter] = useState("mock"),
    [wizard, setWizard] = useState(false),
    [testing, setTesting] = useState(false),
    [active, setActive] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.(false), [onBusyChange]);
  const load = async () => {
    const [m, a] = await Promise.all([
      api<Model[]>("/registry"),
      api<AdapterBundle[]>("/library/adapters"),
    ]);
    setModels(m);
    setAll(a);
  };
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  const work = async (fn: () => Promise<void>) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const open = async (mid: string) => {
    setSelected(mid);
    setPreview(await api<ProjectDetail>(`/library/robots/${mid}/preview`));
    setStep(2);
    setAdapter("mock");
    setTarget("virtual");
    setTesting(false);
  };
  const exportModel = async (mid: string) =>
    download(
      `${mid}.robot.json`,
      JSON.stringify(await api(`/registry/${mid}/bundle`), null, 2),
    );
  const compatible = all.filter(
    (a) => a.model_id === selected && a.category === target,
  );
  const bundle = all.find((a) => a.id === adapter);
  const locked = busy || disabled || active;
  return (
    <section className="global-robot-library">
      <nav className="view-tabs" aria-label="Global robot libraries">
        <button
          className={section === "robots" ? "active" : ""}
          disabled={locked}
          onClick={() => {
            setSection("robots");
            setStep(null);
          }}
        >
          Robots
        </button>
        <button
          className={section === "adapters" ? "active" : ""}
          disabled={locked}
          onClick={() => {
            setSection("adapters");
            setStep(null);
          }}
        >
          Control adapters
        </button>
      </nav>
      <Feedback message={error} />
      {step === null ? (
        <>
          <div className="section-toolbar">
            <div>
              <h3>
                {section === "robots"
                  ? "Global robot library"
                  : "Global control adapter library"}
              </h3>
              <p>
                Reusable across all projects on this installation. Project
                instances pair one robot with one compatible adapter.
              </p>
            </div>
            <button
              className="primary"
              disabled={locked}
              onClick={() => {
                setStep(0);
                setImportMode("json");
                setJSON("");
                setId("");
                setName("");
                setError("");
              }}
            >
              <Plus size={14} /> Add robot to library
            </button>
          </div>
          {section === "robots" ? (
            <div className="library-models">
              {models.map((m) => (
                <article className="config-card" key={m.robot.id}>
                  <span className="tiny-tag">Global robot</span>
                  <h3>{m.robot.name}</h3>
                  <small>
                    {m.robot.id} · {m.robot.version} ·{" "}
                    {Object.keys(m.actuators.actuators).length} actuators
                  </small>
                  <p>{m.robot.description}</p>
                  <p>
                    {all.filter((a) => a.model_id === m.robot.id).length}{" "}
                    configured adapters + 2 virtual templates
                  </p>
                  <div className="section-toolbar">
                    <button
                      className="primary"
                      disabled={locked}
                      onClick={() => void work(() => open(m.robot.id))}
                    >
                      Configure adapters & test
                    </button>
                    {m.source_import?.format === "urdf" && <a className="text-button" href={`/api/registry/${m.robot.id}/source`} download>Download URDF source</a>}
                    <button
                      disabled={locked}
                      onClick={() => void work(() => exportModel(m.robot.id))}
                    >
                      <Download size={14} /> Export definition
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <>
              <p>
                Physical adapters translate to hardware interfaces; virtual
                adapters target simulators. Every library test uses simulated
                feedback and never contacts hardware.
              </p>
              <div className="library-models">
                {all.map((a) => (
                  <article key={a.id} className="config-card">
                    <span className={`tiny-tag target-${a.category}`}>
                      {a.category === "physical" ? "Physical" : "Virtual"}
                    </span>
                    <h3>{a.name}</h3>
                    <p>
                      {a.model_id} · {a.kind} · {a.validation_status}
                    </p>
                    <button
                      disabled={locked}
                      onClick={() =>
                        void work(async () => {
                          await open(a.model_id);
                          setTarget(a.category);
                          setAdapter(a.id);
                        })
                      }
                    >
                      Review robot & adapter
                    </button>
                  </article>
                ))}
              </div>
              <label className="field">
                Robot for a new control adapter
                <select
                  aria-label="Global adapter robot"
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  <option value="">Select global robot</option>
                  {models.map((m) => (
                    <option key={m.robot.id} value={m.robot.id}>
                      {m.robot.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="primary"
                disabled={locked || !selected}
                onClick={() => void work(() => open(selected))}
              >
                Add control adapter
              </button>
            </>
          )}
        </>
      ) : (
        <>
          <ol className="wizard-stages" aria-label="Add global robot progress">
            {[
              "Import robot information",
              "Review robot",
              "Select control adapter",
              "Test & finish",
            ].map((s, i) => (
              <li
                key={s}
                className={step === i ? "active" : step > i ? "done" : ""}
              >
                <span>{i + 1}</span>
                {s}
              </li>
            ))}
          </ol>
          {step === 0 && <div className="view-tabs" aria-label="Robot import format">
            <button disabled={locked} className={importMode === "json" ? "active" : ""} onClick={() => setImportMode("json")}>Robot JSON / template</button>
            <button disabled={locked} className={importMode === "urdf" ? "active" : ""} onClick={() => setImportMode("urdf")}>Import URDF</button>
          </div>}
          {(step === 0 || step === 1) && importMode === "urdf" && <URDFImport key={importKey} disabled={locked} onBusy={setBusy}
            onStage={review => setStep(review ? 1 : 0)} onSaved={async model => { await load(); onChanged(); await open(model.robot.id); }} />}
          {step === 0 && importMode === "json" && (
            <section className="config-card">
              <h3>1. Import robot information</h3>
              <p>
                Use a declarative <strong>.robot.json</strong> bundle: identity,
                actuators and units/limits, kinematic chain, capabilities and
                initial joints. This saves a reusable robot, without adding
                anything to a project.
              </p>
              <p>
                Vendor SDK documentation configures the control adapter in step
                3. URDF/USD geometry is imported in Isaac Sim separately; a mesh
                alone does not define a controllable robot.
              </p>
              <label className="file-button">
                <Upload size={14} /> Import robot definition
                <input
                  aria-label="Import robot definition"
                  type="file"
                  accept=".json,application/json"
                  disabled={locked}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file)
                      void work(async () => {
                        if (file.size > 2000000)
                          throw Error("Definition must be under 2 MB");
                        const text = await file.text();
                        const b = JSON.parse(text);
                        setJSON(text);
                        setId(b.robot?.id ?? "");
                        setName(b.robot?.name ?? "");
                        setStep(1);
                      });
                  }}
                />
              </label>
              <h4>Or start from a robot template</h4>
              <label className="field">
                Template
                <select
                  aria-label="Robot definition template"
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  <option value="">Select template</option>
                  {models.map((m) => (
                    <option key={m.robot.id} value={m.robot.id}>
                      {m.robot.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={locked || !selected}
                onClick={() =>
                  void work(async () => {
                    const b = await api(`/registry/${selected}/bundle`);
                    setJSON(JSON.stringify(b, null, 2));
                    setId("");
                    setName("");
                    setStep(1);
                  })
                }
              >
                Use template
              </button>
            </section>
          )}
          {step === 1 && importMode === "json" && (
            <section className="config-card">
              <h3>2. Review robot definition</h3>
              <p>
                A new robot needs a unique global ID. Review its geometry, joint
                limits and units before saving. A copied template retains its
                original kinematics until you edit them.
              </p>
              <div className="configuration-grid">
                <label className="field">
                  Global robot ID
                  <input
                    aria-label="Global robot ID"
                    value={id}
                    onChange={(e) => setId(e.target.value)}
                    disabled={locked}
                  />
                </label>
                <label className="field">
                  Robot name
                  <input
                    aria-label="Global robot name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    disabled={locked}
                  />
                </label>
              </div>
              <details>
                <summary>Definition details · editable JSON</summary>
                <textarea
                  className="definition-json"
                  aria-label="Robot definition JSON"
                  value={json}
                  onChange={(e) => setJSON(e.target.value)}
                  disabled={locked}
                  spellCheck={false}
                />
              </details>
              <button
                className="primary"
                disabled={locked || !id.trim() || !name.trim()}
                onClick={() =>
                  void work(async () => {
                    const b = JSON.parse(json);
                    b.robot = { ...b.robot, id: id.trim(), name: name.trim() };
                    const m = await post<Model>("/registry/import", b);
                    await load();
                    onChanged();
                    await open(m.robot.id);
                  })
                }
              >
                Save global robot & continue <ArrowRight size={14} />
              </button>
            </section>
          )}
          {step === 2 && preview && (
            <section className="config-card">
              <span className="tiny-tag">Saved in global library</span>
              <h3>3. Control adapter for {preview.model.robot.name}</h3>
              <details>
                <summary>Global joint limits & capabilities</summary>
                <p>
                  Shared by every project using this definition. Editing
                  invalidates compiled plans and adapter validation.
                </p>
                {Object.entries(preview.model.actuators.actuators).map(
                  ([joint, a]) => (
                    <div className="configuration-grid" key={joint}>
                      <strong>
                        {joint} · {a.unit}
                      </strong>
                      {(
                        ["min", "max", "velocity", "acceleration"] as const
                      ).map((k) => (
                        <label className="field" key={k}>
                          {k}
                          <input
                            aria-label={`Global ${joint} ${k}`}
                            type="number"
                            step="any"
                            disabled={locked}
                            value={a[k]}
                            onChange={(e) =>
                              setPreview({
                                ...preview,
                                model: {
                                  ...preview.model,
                                  actuators: {
                                    actuators: {
                                      ...preview.model.actuators.actuators,
                                      [joint]: {
                                        ...a,
                                        [k]: Number(e.target.value),
                                      },
                                    },
                                  },
                                },
                              })
                            }
                          />
                        </label>
                      ))}
                    </div>
                  ),
                )}
                <button
                  disabled={locked}
                  onClick={() =>
                    void work(async () => {
                      await api(`/registry/${selected}/configuration`, {
                        method: "PUT",
                        body: JSON.stringify({
                          actuators: preview.model.actuators.actuators,
                          capabilities: preview.model.capabilities,
                        }),
                      });
                      await load();
                      onChanged();
                      await open(selected);
                    })
                  }
                >
                  Save global definition limits
                </button>
              </details>
              <div
                className="target-choice"
                role="group"
                aria-label="Adapter target"
              >
                <button
                  aria-pressed={target === "virtual"}
                  onClick={() => {
                    setTarget("virtual");
                    setAdapter("mock");
                  }}
                  disabled={locked}
                >
                  Virtual · simulator
                </button>
                <button
                  aria-pressed={target === "physical"}
                  onClick={() => {
                    setTarget("physical");
                    setAdapter("");
                  }}
                  disabled={locked}
                >
                  Physical · robot hardware
                </button>
              </div>
              <p>
                {target === "physical"
                  ? "SDK or ROS 2. Library tests simulate command translation; hardware connection and arming happen on a project instance."
                  : "Built-in simulator or NVIDIA Isaac Sim. Library tests run in the built-in simulator; the project Environment selects the real simulation engine."}
              </p>
              <label className="field">
                Existing compatible adapter
                <select
                  aria-label="Global robot control adapter"
                  value={adapter}
                  disabled={locked}
                  onChange={(e) => setAdapter(e.target.value)}
                >
                  <option value="">Choose adapter</option>
                  {target === "virtual" && (
                    <>
                      <option value="mock">
                        Built-in simulator · virtual template
                      </option>
                      <option value="isaac_sim">
                        NVIDIA Isaac Sim · virtual template
                      </option>
                    </>
                  )}
                  {compatible.map((a) => (
                    <option value={a.id} key={a.id}>
                      {a.name} · {a.validation_status}
                    </option>
                  ))}
                </select>
              </label>
              <div className="section-toolbar">
                <button disabled={locked} onClick={() => setWizard(true)}>
                  Create adapter from documentation / custom commands
                </button>
                <button
                  className="primary"
                  disabled={locked || !adapter}
                  onClick={() => {
                    setStep(3);
                    setTesting(true);
                  }}
                >
                  Continue to test <ArrowRight size={14} />
                </button>
              </div>
            </section>
          )}
          {step === 3 && preview && (
            <section className="config-card">
              <h3>4. Test {preview.model.robot.name}</h3>
              <p>
                <strong>
                  {target === "physical"
                    ? "Physical adapter · simulated transport"
                    : "Virtual adapter · built-in simulator test"}
                </strong>
                . This preview creates no project instance and never connects to
                hardware.
              </p>
              {testing && (
                <AdapterControls
                  key={adapter}
                  detail={preview}
                  robot={preview.robots[0]}
                  adapter={bundle ?? adapter}
                  globalModelId={selected}
                  testOnly
                  onEnvironmentChanged={() => {}}
                  onSessionChange={setActive}
                />
              )}
              <button
                className="primary"
                disabled={locked}
                onClick={() => {
                  setTesting(false);
                  setStep(null);
                  onChanged();
                }}
              >
                Finish · return to global library
              </button>
            </section>
          )}
          <div className="section-toolbar">
            <button
              disabled={locked}
              onClick={() => {
                setTesting(false);
                if (step === 3) setStep(2);
                else if (step === 1) { setStep(0); if (importMode === "urdf") setImportKey(k => k + 1); }
                else setStep(null);
              }}
            >
              <ArrowLeft size={14} />{" "}
              {step === 3 || step === 1 ? "Back" : "Return to library"}
            </button>
          </div>
        </>
      )}
      {wizard && preview && (
        <AdapterWizard
          detail={preview}
          robot={preview.robots[0]}
          globalModelId={selected}
          onClose={() => {
            setWizard(false);
            void load();
          }}
          onGenerated={(a) => {
            setAll((prev) => [a, ...prev.filter((b) => b.id !== a.id)]);
            setAdapter(a.id);
            setTarget(a.category);
            if(a.reviewed_hash===a.hash&&a.test_report?.passed)onChanged();
          }}
        />
      )}
    </section>
  );
}

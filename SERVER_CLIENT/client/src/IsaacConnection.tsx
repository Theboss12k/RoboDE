import Feedback from "./ui/Feedback";
import NvidiaLogo from "./branding/NvidiaLogo";
import { useEffect, useState } from "react";
import { api, post } from "./api";
import { desktop, type IsaacFileKind } from "./desktop";

type Deployment = "local" | "gcp" | "remote" | "nebius";
type Settings = {
  deployment: Deployment;
  url: string;
  has_token: boolean;
  load_scene: boolean;
  gcp_project: string;
  gcp_zone: string;
  gcp_instance: string;
  on_demand: boolean;
  idle_minutes: number;
  max_session_minutes: number;
  use_iap: boolean;
  ssh_key_file: string;
  local_launcher: string;
  local_source: string;
  local_source_kind: "automatic" | "catalog" | "manifest";
  local_gui: boolean;
  nebius_host: string;
  nebius_ssh_user: string;
};
type Host = {
  platform: string;
  local_supported: boolean;
  gcloud_available: boolean;
  nvidia_tools_available: boolean;
  supported_version: string;
};
type Runtime = { status: string; message: string; managed: boolean };
type GPU = {status:string;message:string;configured?:boolean;cloud_apps?:{ide?:string;business?:string}};
const defaults: Settings = {
  deployment: "remote",
  url: "http://127.0.0.1:9100",
  has_token: false,
  load_scene: false,
  gcp_project: "",
  gcp_zone: "",
  gcp_instance: "",
  on_demand: false,
  idle_minutes: 10,
  max_session_minutes: 120,
  use_iap: true,
  ssh_key_file: "",
  local_launcher: "",
  local_source: "",
  local_source_kind: "automatic",
  local_gui: true,
  nebius_host: "",
  nebius_ssh_user: "ubuntu",
};

function shellArgument(value: string) {
  return "'" + value.replaceAll("'", "'\"'\"'") + "'";
}

export default function IsaacConnection({
  disabled,
  onChanged,
}: {
  disabled: boolean;
  onChanged?: () => void | Promise<void>;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [host, setHost] = useState<Host | null>(null);
  const [runtime, setRuntime] = useState<Runtime>({
    status: "stopped",
    message: "Local Isaac Sim is stopped.",
    managed: false,
  });
  const [gpu, setGpu] = useState<GPU | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false),
    [expanded, setExpanded] = useState(false);
  const [error, setError] = useState(""),
    [status, setStatus] = useState(""),
    [log, setLog] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void api<Settings>("/configuration/isaac")
      .then((s) => {
        if (active) setSettings({ ...defaults, ...s });
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    void api<Host>("/configuration/isaac/setup")
      .then((s) => {
        if (active) setHost(s);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!expanded || settings?.deployment !== "local") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const state = await api<Runtime>("/configuration/isaac/local");
        if (active) setRuntime(state);
      } catch {
        /* Explicit operations report connection errors. */
      }
      if (active) timer = setTimeout(poll, 1500);
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [expanded, settings?.deployment]);
  useEffect(() => {
    if (gpu?.status !== "starting") return;
    let active = true;
    const timer = setInterval(() => {
      void api<GPU>("/configuration/isaac/gpu").then(next => {
        if (!active) return;
        setGpu(next);
        if (next.status === "error") { setStatus(""); setError(next.message); }
        else setStatus(next.message);
      }).catch(e => { if (active) setError(e.message); });
    }, 1500);
    return () => { active = false; clearInterval(timer); };
  }, [gpu?.status]);
  const locked = disabled || busy || runtime.managed;
  const update = (change: Partial<Settings>) => {
    setSettings((s) => s && { ...s, ...change });
    setDirty(true);
    setStatus("");
  };
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const choose = (kind: IsaacFileKind) =>
    void work(async () => {
      const path = await desktop?.chooseIsaacFile(kind);
      if (path)
        update(
          kind === "launcher"
            ? { local_launcher: path }
            : { local_source: path },
        );
    });
  const selectDeployment = (deployment: Deployment) => {
    update({
      deployment,
      on_demand: deployment === "gcp",
      ...(deployment === "local" || deployment === "nebius"
        ? {
            url: "http://127.0.0.1:9100",
            load_scene: deployment === "nebius" || settings?.local_source_kind !== "manifest",
          }
        : {}),
    });
  };
  async function save() {
    if (!settings) return;
    const { has_token, ...data } = settings;
    void has_token;
    const result = await api<Settings>("/configuration/isaac", {
      method: "PUT",
      body: JSON.stringify({ ...data, token: token || null }),
    });
    setSettings(result);
    setToken("");
    setDirty(false);
    setStatus(
      "Connection saved. Select NVIDIA Isaac Sim in Environment to start it and transfer the project scene automatically.",
    );
  }
  const localOperation = (action: "start" | "stop" | "check") =>
    void work(async () => {
      const result = await post<Runtime>(
        `/configuration/isaac/local/${action}`,
      );
      if (action !== "check") setRuntime(result);
      setStatus(result.message);
      if (action === "stop") await onChanged?.();
    });
  return (
    <details
      className="config-card isaac-connection"
      onToggle={(e) => setExpanded(e.currentTarget.open)}
    >
      <summary>
        <span className="nvidia-tool-heading">
          <NvidiaLogo />
          <span><span className="sr-only">NVIDIA </span>Isaac Sim setup</span>
        </span>
      </summary>
      <p>
        Choose where Isaac runs. RoboDE uses the same robot controls, project
        scene and planning engine with either deployment.
      </p>
      <Feedback message={error} />
      <Feedback message={status} kind="info" />
      {settings && (
        <>
          <div
            className="isaac-targets"
            role="group"
            aria-label="Isaac deployment target"
          >
            <button
              type="button"
              aria-pressed={settings.deployment === "nebius"}
              disabled={locked}
              onClick={() => selectDeployment("nebius")}
            >
              <strong>Nebius GPU VM</strong>
              <span>
                You start the VM in the Nebius console · RoboDE connects over SSH
              </span>
            </button>
            <button
              type="button"
              aria-pressed={settings.deployment === "gcp"}
              disabled={locked}
              onClick={() => selectDeployment("gcp")}
            >
              <strong>GCP GPU VM</strong>
              <span>
                Recommended on macOS · start when needed, shut down when idle
              </span>
            </button>
            <button
              type="button"
              aria-pressed={settings.deployment === "local"}
              disabled={locked}
              onClick={() => selectDeployment("local")}
            >
              <strong>This computer</strong>
              <span>
                Installed Isaac Sim · Windows / Linux with a supported NVIDIA
                GPU
              </span>
            </button>
          </div>
          <button
            type="button"
            className="isaac-advanced"
            aria-pressed={settings.deployment === "remote"}
            disabled={locked}
            onClick={() => selectDeployment("remote")}
          >
            Existing worker · advanced connection
          </button>
          <p className="inline-note">
            {desktop ? "Desktop configuration" : "Server configuration"} ·{" "}
            {host?.platform ?? "checking host"}. Local paths and tools refer to
            the computer running the IDE backend.
          </p>
          {settings.deployment === "nebius" && (
            <NebiusSetup settings={settings} locked={locked} update={update} dirty={dirty}
              onStatus={setStatus} onError={setError} onChanged={onChanged} />
          )}
          {settings.deployment === "gcp" && (
            <section
              className="isaac-setup-section"
              aria-label="GCP Isaac setup"
            >
              <h3>1. Prepare your GPU VM</h3>
              <ol className="isaac-checklist">
                <li>
                  Create a Google Cloud project with billing and GPU quota, then
                  a supported RTX GPU VM.{" "}
                  <a
                    href="https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_advanced_cloud_setup_gcp.html"
                    target="_blank"
                    rel="noreferrer"
                  >
                    NVIDIA GCP setup ↗
                  </a>
                </li>
                <li>
                  Install Isaac Sim 6.2, copy the RoboDE server to the VM,
                  and install its worker dependencies with Isaac’s Python. Start
                  the worker with --project-scene for automatic demo robot and
                  scene loading. Manufacturer robots use an approved USD
                  catalog.
                </li>
                <li>
                  Install the independent idle-shutdown service and a provider
                  STOP runtime limit. Run the authenticated worker bound to VM
                  loopback; use a remote desktop for Isaac’s native viewport.
                </li>
                <li>
                  Install Google Cloud CLI on this IDE host and sign in with
                  your own account.{" "}
                  {host &&
                    (host.gcloud_available
                      ? "Google Cloud CLI was found."
                      : "Google Cloud CLI was not found on the IDE host.")}
                </li>
              </ol>
              <pre className="connection-example">gcloud auth login</pre>
              <a
                href="https://cloud.google.com/sdk/docs/install"
                target="_blank"
                rel="noreferrer"
              >
                Install Google Cloud CLI ↗
              </a>
              <h3>2. Connect the VM</h3>
              <div className="coordinate-inputs">
                {(["gcp_project", "gcp_zone", "gcp_instance"] as const).map(
                  (key) => (
                    <label key={key}>
                      {key.replace("gcp_", "")}
                      <input
                        aria-label={`GCP ${key.replace("gcp_", "")}`}
                        value={settings[key]}
                        disabled={locked}
                        onChange={(e) => update({ [key]: e.target.value })}
                      />
                    </label>
                  ),
                )}
              </div>
              <details>
                <summary>SSH authentication</summary>
                <label className="field">
                  Private key file on the IDE server
                  <input
                    aria-label="GCP SSH key file"
                    value={settings.ssh_key_file}
                    disabled={locked}
                    placeholder="Optional absolute path; blank uses the Google Cloud default"
                    onChange={(e) => update({ ssh_key_file: e.target.value })}
                  />
                </label>
                <p>The private key stays on the IDE host. Google Cloud receives its public key with a two-hour expiration on each connection.</p>
              </details>
              <label>
                <input
                  type="checkbox"
                  aria-label="On-demand GPU"
                  checked={settings.on_demand}
                  disabled={locked}
                  onChange={(e) => update({ on_demand: e.target.checked })}
                />{" "}
                Start GPU on demand; require an independent idle watchdog and
                provider runtime limit
              </label>
              {settings.on_demand && (
                <div className="coordinate-inputs">
                  {(["idle_minutes", "max_session_minutes"] as const).map(
                    (key) => (
                      <label key={key}>
                        {key === "idle_minutes"
                          ? "Idle shutdown · minutes"
                          : "Maximum GPU session · minutes"}
                        <input
                          aria-label={
                            key === "idle_minutes"
                              ? "Idle shutdown minutes"
                              : "Maximum GPU session minutes"
                          }
                          type="number"
                          min={key === "idle_minutes" ? 1 : 10}
                          max={key === "idle_minutes" ? 120 : 480}
                          value={settings[key]}
                          disabled={locked}
                          onChange={(e) =>
                            update({ [key]: Number(e.target.value) })
                          }
                        />
                      </label>
                    ),
                  )}
                  <label>
                    <input
                      type="checkbox"
                      aria-label="Use IAP for SSH"
                      checked={settings.use_iap}
                      disabled={locked}
                      onChange={(e) => update({ use_iap: e.target.checked })}
                    />{" "}
                    Use IAP for SSH
                  </label>
                </div>
              )}
              <p>
                Opening this panel does not start or create a VM. With on-demand
                enabled, Start or Connect opens the tunnel and checks shutdown
                safeguards. Otherwise open this tunnel yourself:
              </p>
              <pre className="connection-example">{`gcloud compute ssh ${settings.gcp_instance || "VM_NAME"} --project=${settings.gcp_project || "PROJECT_ID"} --zone=${settings.gcp_zone || "ZONE"}${settings.ssh_key_file ? ` --ssh-key-file=${shellArgument(settings.ssh_key_file)} --ssh-key-expire-after=2h` : ""}${settings.use_iap ? " --tunnel-through-iap" : ""} -- -N -L 9100:127.0.0.1:9100`}</pre>
            </section>
          )}
          {settings.deployment === "local" && (
            <section
              className="isaac-setup-section"
              aria-label="Local Isaac setup"
            >
              <h3>1. Select your local installation</h3>
              {host && !host.local_supported && (
                <p className="inline-error">
                  Isaac Sim cannot run natively on macOS. Select GCP GPU VM, or
                  attach to an existing Windows/Linux GPU worker. Local launch
                  is unavailable on this host.
                </p>
              )}
              <p>
                Install Isaac Sim 6.2 and run NVIDIA’s compatibility checker
                first. Accept NVIDIA’s license in its installer. The IDE
                launches your installation; it does not include Isaac Sim or
                download drivers.
              </p>
              <a
                href="https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_workstation.html"
                target="_blank"
                rel="noreferrer"
              >
                Install Isaac Sim and check compatibility ↗
              </a>
              <label className="field">
                Isaac Python launcher
                <div className="isaac-path">
                  <input
                    aria-label="Local Isaac launcher"
                    value={settings.local_launcher}
                    placeholder={
                      host?.platform === "win32"
                        ? "C:\\isaacsim\\python.bat"
                        : "/opt/isaacsim/python.sh"
                    }
                    disabled={locked}
                    onChange={(e) => update({ local_launcher: e.target.value })}
                  />
                  {desktop && (
                    <button
                      type="button"
                      aria-label="Choose Isaac launcher"
                      disabled={locked}
                      onClick={() => choose("launcher")}
                    >
                      Browse…
                    </button>
                  )}
                </div>
              </label>
              <p>
                Install the worker packages once using the selected Isaac Python
                environment:
              </p>
              <pre className="connection-example">{`${settings.local_launcher ? (host?.platform === "win32" ? "& " : "") + JSON.stringify(settings.local_launcher) : "ISAAC_PYTHON"} -m pip install -r SERVER_CLIENT/server/requirements-worker.txt`}</pre>
              <h3>2. Choose the native scene</h3>
              <label className="field">
                Scene source
                <select
                  aria-label="Local Isaac scene source"
                  disabled={locked}
                  value={settings.local_source_kind}
                  onChange={(e) =>
                    update({
                      local_source_kind: e.target.value as
                        | "automatic"
                        | "catalog"
                        | "manifest",
                      local_source: "",
                      load_scene: e.target.value !== "manifest",
                    })
                  }
                >
                  <option value="automatic">
                    Automatic project scene · no scene file required
                  </option>
                  <option value="catalog">
                    Approved robot USD catalog · load project robots and edit
                    objects
                  </option>
                  <option value="manifest">
                    Fixed cell manifest · attach to a prepared scene
                  </option>
                </select>
              </label>
              {settings.local_source_kind !== "automatic" && (
                <label className="field">
                  {settings.local_source_kind === "catalog"
                    ? "Approved asset catalog"
                    : "Fixed scene manifest"}
                  <div className="isaac-path">
                    <input
                      aria-label="Local Isaac scene file"
                      value={settings.local_source}
                      placeholder="Absolute path to catalog.yaml or worker.yaml"
                      disabled={locked}
                      onChange={(e) => update({ local_source: e.target.value })}
                    />
                    {desktop && (
                      <button
                        type="button"
                        aria-label="Choose Isaac scene file"
                        disabled={locked}
                        onClick={() =>
                          choose(
                            settings.local_source_kind === "catalog"
                              ? "catalog"
                              : "manifest",
                          )
                        }
                      >
                        Browse…
                      </button>
                    )}
                  </div>
                </label>
              )}
              <p>
                Automatic mode builds the registered educational demo robots and
                transfers the project’s objects and placements. Manufacturer
                robots need a USD model and joint mapping once in a catalog. A
                fixed manifest attaches to an existing cell and cannot receive a
                scene transfer.
              </p>
              <details>
                <summary>Demo scene and catalog examples</summary>
                <p>
                  From PROJECT, create a fictional demo cell with Isaac’s Python
                  (this is a fixed manifest):
                </p>
                <pre className="connection-example">{`${settings.local_launcher ? (host?.platform === "win32" ? "& " : "") + JSON.stringify(settings.local_launcher) : "ISAAC_PYTHON"} -m simulation.isaac_sim.build_demo_scene --project apple_transfer --output "${host?.platform === "win32" ? "C:\\robot-assets\\demo" : "/data/robot-assets/demo"}"`}</pre>
                <p>
                  The launcher runs from SERVER_CLIENT/server; run the demo
                  command there too. Select the generated worker.yaml as a fixed
                  scene manifest.
                </p>
                <pre className="connection-example">{`# Catalog for project robot loading; replace with your approved assets.\nrobots:\n  your_model_id:\n    usd: /absolute/path/robot.usd\n    sha256: REPLACE_WITH_USD_SHA256\n    articulation_path: ""\n    joints:\n      actuator_id: usd_joint_name`}</pre>
              </details>
              <label>
                <input
                  type="checkbox"
                  aria-label="Open native Isaac window"
                  checked={settings.local_gui}
                  disabled={locked}
                  onChange={(e) => update({ local_gui: e.target.checked })}
                />{" "}
                Open the native Isaac Sim window beside the IDE
              </label>
              <p>
                The local worker stops when this IDE backend exits. A simulator
                window on a server appears on that server’s desktop.
              </p>
            </section>
          )}
          {settings.deployment === "remote" && (
            <p>
              Attach to an already running authenticated Isaac worker. Use HTTPS
              remotely or a loopback SSH tunnel. RoboDE does not own or shut
              down this external process.
            </p>
          )}
          <h3>
            {settings.deployment === "remote"
              ? "Worker connection"
              : "3. Save and test"}
          </h3>
          <label className="field">
            Worker URL
            <input
              aria-label="Isaac worker URL"
              value={settings.url}
              disabled={locked}
              onChange={(e) => update({ url: e.target.value })}
            />
          </label>
          <label className="field">
            Worker token
            {settings.has_token && (
              <small>Saved · leave blank to keep it</small>
            )}
            <input
              aria-label="Isaac worker token"
              type="password"
              autoComplete="new-password"
              value={token}
              disabled={locked}
              onChange={(e) => {
                setToken(e.target.value);
                setDirty(true);
              }}
            />
          </label>
          <button
            type="button"
            disabled={locked}
            onClick={() =>
              void work(async () => {
                const data = await post<{ token: string }>(
                  "/configuration/isaac/token",
                );
                setToken(data.token);
                setDirty(true);
                setStatus(
                  "New token drafted. Save it here and use the same token on a remote worker. A managed local worker receives it automatically.",
                );
              })
            }
          >
            Generate worker token
          </button>
          <label className="isaac-load-scene">
            <input
              aria-label="Load project robots on connect"
              type="checkbox"
              checked={settings.load_scene}
              disabled={
                locked ||
                (settings.deployment === "local" &&
                  settings.local_source_kind === "manifest")
              }
              onChange={(e) => update({ load_scene: e.target.checked })}
            />{" "}
            Rebuild scene on a fresh connection (advanced)
          </label>
          <p>
            Switching simulators always transfers the current scene
            automatically to a managed worker, including current joint
            positions. This setting only controls fresh connections without a
            simulator switch. Reset applies saved starting positions. Imported
            meshes use static geometry, neutral materials and bounding-box
            collisions in Isaac Sim.
          </p>
          {dirty && (
            <p className="inline-note">
              Unsaved settings. Save before testing or starting the simulator.
            </p>
          )}
          <div className="section-toolbar">
            <button
              type="button"
              disabled={locked}
              onClick={() => void work(save)}
            >
              Save worker connection
            </button>
            <button
              type="button"
              disabled={disabled || busy || dirty}
              onClick={() =>
                void work(async () => {
                  const h = await post<Record<string, unknown>>(
                    "/configuration/isaac/probe",
                  );
                  setStatus(
                    `Connected to ${h.engine} ${h.simulator_version} · ${h.scene_loading ? "robot loading available" : "prebuilt scene"} · native GPU acceptance still required`,
                  );
                })
              }
            >
              Test saved connection
            </button>
          </div>
          {settings.deployment === "local" && (
            <section className="isaac-runtime" aria-label="Local Isaac runtime">
              <strong>Local simulator · {runtime.status}</strong>
              <p role="status">{runtime.message}</p>
              <div className="section-toolbar">
                <button
                  type="button"
                  disabled={
                    disabled ||
                    busy ||
                    dirty ||
                    runtime.managed ||
                    !host?.local_supported
                  }
                  onClick={() => localOperation("check")}
                >
                  Check local setup
                </button>
                <button
                  type="button"
                  className="primary"
                  disabled={
                    disabled ||
                    busy ||
                    dirty ||
                    runtime.managed ||
                    !host?.local_supported
                  }
                  onClick={() => localOperation("start")}
                >
                  Start local Isaac Sim
                </button>
                <button
                  type="button"
                  disabled={disabled || busy || !runtime.managed}
                  onClick={() => localOperation("stop")}
                >
                  Stop local Isaac Sim
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void work(async () =>
                      setLog(
                        (
                          await api<{ text: string }>(
                            "/configuration/isaac/local/log",
                          )
                        ).text,
                      ),
                    )
                  }
                >
                  View simulator log
                </button>
              </div>
              {log !== null && (
                <pre className="isaac-log">
                  {log || "No local worker log yet."}
                </pre>
              )}
            </section>
          )}
          {settings.deployment === "gcp" && settings.on_demand && (
           <>
            <div className="section-toolbar">
              {(["start", "stop"] as const).map((action) => (
                <button
                  type="button"
                  key={action}
                  disabled={disabled || busy || dirty}
                  onClick={() =>
                    void work(async () => {
                      const result = await post<GPU>(
                        `/configuration/isaac/gpu/${action}`,
                      );
                      setGpu(result);
                      if (result.status === "error") setError(result.message);
                      else setStatus(result.message);
                      if (action === "stop") await onChanged?.();
                    })
                  }
                >
                  {action === "start" ? "Start GPU VM" : "Stop GPU VM"}
                </button>
              ))}
              <button
                type="button"
                disabled={busy || dirty}
                onClick={() =>
                  void work(async () =>
                    api<GPU>("/configuration/isaac/gpu?refresh=true").then(next => {
                      setGpu(next);
                      if (next.status === "error") setError(next.message);
                      else setStatus(next.message);
                    }),
                  )
                }
              >
                Check GPU status
              </button>
            </div>
            {gpu?.status==='ready' && gpu.cloud_apps && <div className="section-toolbar cloud-app-links">
              {(['ide','business'] as const).map(key=>{
                const href=gpu.cloud_apps?.[key];
                if(!href || !/^(https:\/\/[a-z0-9-]+\.trycloudflare\.com|http:\/\/127\.0\.0\.1:1808[34])\/?$/.test(href))return null;
                return <a key={key} className="secondary" href={href} target="_blank" rel="noreferrer">Open cloud {key==='ide'?'IDE':'Business App'}</a>;
              })}
              <small>Cloud apps stop with the VM. Public session links change after restart.</small>
            </div>}
           </>
          )}
        </>
      )}
    </details>
  );
}

type Nebius = { configured: boolean; status: string; message: string; host?: string; idle_guard_active?: boolean };
/** Connect-only Nebius target: the operator owns the VM lifecycle; RoboDE opens an SSH tunnel to its worker. */
function NebiusSetup({ settings, locked, update, dirty, onStatus, onError, onChanged }: { settings: Settings; locked: boolean; update: (patch: Partial<Settings>) => void; dirty: boolean;
  onStatus: (m: string) => void; onError: (m: string) => void; onChanged?: () => void | Promise<void> }) {
  const [state, setState] = useState<Nebius | null>(null), [busy, setBusy] = useState(false);
  useEffect(() => { void api<Nebius>("/configuration/isaac/nebius").then(setState).catch(() => {}); }, [settings.nebius_host]);
  const act = (path: "connect" | "disconnect") => {
    setBusy(true); onError("");
    void post<Nebius>(`/configuration/isaac/nebius/${path}`).then((r) => { setState(r); onStatus(r.message); return onChanged?.(); })
      .catch((e) => onError((e as Error).message)).finally(() => setBusy(false));
  };
  return (
    <section className="isaac-setup-section" aria-label="Nebius Isaac setup">
      <h3>1. Start your Nebius GPU VM</h3>
      <ol className="isaac-checklist">
        <li>In the Nebius console, create a VM with an NVIDIA RTX GPU (for example L40S). A100 and H100 lack the RT cores Isaac Sim needs.</li>
        <li>Install Isaac Sim and the RoboDE worker with <code>scripts/bootstrap_isaac_vm.sh</code>, and set the worker token shown below.</li>
        <li>Start the VM before simulating. RoboDE does not start, stop or create it; the guest idle watchdog powers it off.</li>
      </ol>
      <h3>2. Connect</h3>
      <div className="configuration-grid">
        <label className="field">VM public IP or hostname<input aria-label="Nebius VM address" value={settings.nebius_host} disabled={locked} placeholder="203.0.113.10" onChange={(e) => update({ nebius_host: e.target.value.trim() })} /></label>
        <label className="field">SSH user<input aria-label="Nebius SSH user" value={settings.nebius_ssh_user} disabled={locked} onChange={(e) => update({ nebius_ssh_user: e.target.value.trim() })} /></label>
      </div>
      <label className="field">SSH private key on the RoboDE server · optional<input aria-label="Nebius SSH key file" value={settings.ssh_key_file} disabled={locked} placeholder="/Users/you/.ssh/id_ed25519" onChange={(e) => update({ ssh_key_file: e.target.value.trim() })} /></label>
      <div className="section-toolbar">
        <button className="primary" type="button" disabled={locked || busy || dirty || !settings.nebius_host || state?.status === "ready"} onClick={() => act("connect")}>{busy ? "Connecting…" : "Connect to Nebius VM"}</button>
        <button type="button" disabled={locked || busy || state?.status !== "ready"} onClick={() => act("disconnect")}>Disconnect</button>
      </div>
      {dirty && <small>Save the connection before connecting.</small>}
      {state && <p className="inline-note" role="status">{state.status === "ready" ? "Connected" : state.status === "error" ? "Not connected" : "Disconnected"} · {state.message}{state.status === "ready" && !state.idle_guard_active ? " The VM's idle watchdog is not running; stop the VM yourself when finished." : ""}</p>}
    </section>
  );
}

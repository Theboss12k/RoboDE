# Electron application (existing desktop version)

The existing sandboxed Electron shell lives here. It uses the canonical React IDE in `SERVER_CLIENT/client` and Python runtime in `SERVER_CLIENT/server`, so the desktop and browser versions retain the same features, Monaco editor, tutorial, controls, planning engine and saved data.

From PROJECT:

```sh
npm ci --ignore-scripts
npm run setup
npm run dev
```

For a built desktop UI:

```sh
npm run build
npm run electron:start
```

The launcher starts the loopback API, waits for it, then opens Electron. Quit the window or press Ctrl+C to stop its child processes. The browser server is launched separately with `npm run server:start`; stop it before starting a second local calculation runtime on the same default port. The backend is shared source code, rather than duplicated under this directory.

## NVIDIA Isaac Sim: GCP or local

Open **Environment → Isaac Sim setup**. Choose:

- **GCP GPU VM** on macOS (also available on Windows/Linux). Enter the existing GPU VM's project, zone, instance and worker token. On-demand mode preserves the independent idle watchdog and provider STOP duration checks; opening setup never boots a VM. The app starts/stops the configured VM and opens its SSH tunnel after those safeguards are configured. VM provisioning, billing and NVIDIA installation remain account-owner setup steps, explained in [the GCP walkthrough](../docs/GCP_ISAAC.md).
- **This computer** on a supported Windows/Linux NVIDIA GPU host. Browse to Isaac Sim 6.2's `python.sh` / `python.bat` (or an Isaac-enabled Python executable), keep **Automatic project scene** selected (no scene file for demo robots), generate a worker token, and save. Select **NVIDIA Isaac Sim** in Environment to start the worker, wait for readiness and transfer robots, current poses and objects automatically. Manufacturer robots use a USD catalog configured once; fixed manifests are advanced attach-only mode. The GUI checkbox opens native Isaac alongside the IDE. Status and a redacted log are available in the panel; Stop and backend shutdown terminate only the worker launched by this backend.
- **Existing worker** for an already running local/tunneled/HTTPS endpoint whose lifecycle is managed externally. Legacy saved endpoints keep this attach-only behavior; upgrading does not start anything.

Isaac is not bundled with the IDE and cannot run natively on macOS. Install it using [NVIDIA's workstation instructions](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_workstation.html), accept its license and run the compatibility checker. Install `SERVER_CLIENT/server/requirements-worker.txt` into that Isaac Python environment once. See [local setup details](../docs/ISAAC_SIM.md). Native GPU and physical acceptance are separate from the process/HTTP contract tests.

The file-picker bridge is restricted to the trusted main IDE frame and three file-selection types. The renderer keeps sandboxing, context isolation and Node integration disabled. Only the backend launches the worker; it owns one process and prevents conflicting connection edits while that worker or robot controls are active. Local paths always refer to the backend host, including when the same UI is opened in a browser.

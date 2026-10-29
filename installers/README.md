# RoboDE installers · 0.4.0

Choose an edition. The desktop and hosted IDE share the same React UI, robot library, planner and native Isaac worker. The Business App connects to the server’s shared workspace:

| Mode | IDE | Business App | Network |
| --- | --- | --- | --- |
| RTX server | Browser, calculations on the server | Served by the same backend | IDE 8081, Business 8080; configure HTTPS |
| RTX desktop | Sandboxed Electron, local calculations | Local room manager; phone exports are imported manually | Loopback only, no LAN listener |
| Mac desktop | Sandboxed Electron; built-in simulation locally, Isaac on GCP/remote RTX | Import phone captures manually | Loopback only |
| Business companion | Browser app / Home Screen app | Uses the installed server’s planning engine and project state | HTTPS Business App URL; no GPU needed on client |

Supported installer targets: **Ubuntu 24.04 x64** (22.04 is deprecated by NVIDIA) and **Windows 11 x64**. Python **3.12** is required for local RTX setup. Mac remote setup supports Python **3.12 or 3.13**, on Apple Silicon or Intel using the matching download. The installer creates separate API and Isaac environments. No Node/npm installation is needed on the target machine. Setup downloads dependencies; a desktop can run locally afterward using cached assets, local templates and custom command recipes. Hosted LLM providers and uncached NVIDIA assets still require connectivity.

An arbitrary RTX card is not a compatibility guarantee. NVIDIA's published Isaac 6.2 baseline is RTX 4080 / 16 GB VRAM / 32 GB RAM. Local RTX setup checks the OS and NVIDIA GPU/VRAM, then pins the worker to Isaac 6.2.x; run NVIDIA's compatibility checker for complete driver/rendering validation. Drivers are installed separately. GPUs without RT cores are unsupported. See [NVIDIA requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html) and [Python installation](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_python.html).

## Install

Extract the ZIP for your OS and desired mode. Check its SHA-256 against the supplied `.sha256` file. Read the [NVIDIA EULA](https://docs.omniverse.nvidia.com/eula); pass the acceptance option only if you agree.

Ubuntu, installing Isaac as well:

```sh
bash install-server.sh --directory "$HOME/RobotIDE-Server" --install-isaac --accept-nvidia-eula --service
# Or a fully local desktop:
bash install-desktop.sh --directory "$HOME/RobotIDE-Desktop" --install-isaac --accept-nvidia-eula
```

Windows PowerShell, as the Windows user who will run the app:

```powershell
.\install-server.ps1 --directory "$env:LOCALAPPDATA\RobotIDE-Server" --install-isaac --accept-nvidia-eula
# Or:
.\install-desktop.ps1 --directory "$env:LOCALAPPDATA\RobotIDE-Desktop" --install-isaac --accept-nvidia-eula
```

To use an existing **Isaac 6.2 Python executable**, replace `--install-isaac` with `--isaac-python /absolute/path/to/isaac-environment/bin/python` (Windows: `C:\path\isaac-environment\Scripts\python.exe`). Setup installs the bridge's pinned dependencies into that environment; choose an environment dedicated to Robot IDE. Shell/batch launchers cannot be passed to the installer, although the IDE's interactive local setup supports NVIDIA launchers. Windows long-path support may be necessary for NVIDIA dependencies.

`--check` performs a read-only OS/GPU preflight. Allow at least 60 GiB free for a new Isaac environment and caches. First simulation/shader setup may take several minutes. The installer does not change NVIDIA drivers, firewall rules, GCP configuration or ROS infrastructure.

On Linux desktops with restricted user namespaces, Electron may need its sandbox helper configured by an administrator. Rerun with `--configure-sandbox` to apply root ownership and mode 4755 to the verified Electron sandbox helper. The application keeps Electron sandboxing enabled. Run the desktop as a normal graphical-session user, never root.

## Start, stop and update

Setup creates `start.sh` on Ubuntu or `Start Robot IDE.cmd` on Windows in the installation directory. The server starts both authenticated sites; the desktop opens Electron. The generated team code is stored in the owner-only `access.json` file, never included in release archives or printed into a service log. Windows setup restricts the installation directory ACL to the installing user.

Ubuntu server `--service` installs/enables a **user** systemd service. Use `systemctl --user status|stop|start robot-ide`; an administrator can enable `loginctl enable-linger USER` for startup without login. Windows server runs under the interactive user; for login startup create a Task Scheduler task launching the installed Python with `run.py` as its argument. An unattended Windows service deployment is not included. Do not run the Electron desktop in a service session.

Console mode stops with Ctrl+C. For a second isolated installation, run the installed Python with `run.py --port-offset 10000`; the API/IDE/Business ports then become 18765/18081/18080. Use a different installation/data directory. Closing Electron stops the owned API and simulator workers. The supervisor checks port ownership, fails as a unit if a child exits, and shuts down its owned processes. No GCP VM is started by these installers. In Environment select **NVIDIA Isaac Sim** to start the local worker when needed; use its Stop control to release the GPU.

Data lives under `<installation>/data`, independently of versioned code in `<installation>/releases`. Rerun setup at the same location to update; initial examples and credentials are seeded only if absent. Stop the app before updating. Keep a data backup. To uninstall, stop/disable its service, remove the user unit if installed, then remove the installation directory; copy its `data` directory first if you want to retain projects and history.

## Hosted HTTPS and phone access

The server binds its authenticated IDE to 8081 and limited Business gateway to 8080. The calculation API stays on `127.0.0.1:8765`; native workers also stay on loopback. Open only intended gateway ports in your firewall. Use a VPN or TLS reverse proxy before internet access; plain HTTP is for trusted LAN testing. Microphone/live camera APIs require a secure context on phones.

With Caddy installed and two DNS names pointing to the server, use a configuration like this, replacing both names:

```caddyfile
ide.example.com {
    reverse_proxy 127.0.0.1:8081
}
workspace.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

The browser shows the IDE's live 3D representation of observed physics. This release does **not** install Isaac's native WebRTC editor/video stream. Both web apps share the same project state and ownership rules.

## Offline mobile room captures

The Business App's Room capture page links **Offline capture**. Its self-contained `room-capture.html` is also in the installed `BUSINESS_APP/dist` folder. Open it on the phone in a browser, take/select JPG/PNG photographs and **Export room capture (.zip)**. HTTPS-served capture pages cache themselves for offline reopening. Phone file-preview apps may disable JavaScript; open the page in a browser or load the HTTPS page before going offline. Photographs stay in the phone browser until exported or cleared.

Transfer the ZIP manually to the offline desktop. In the IDE use **Environment → Import room capture from mobile / USDZ**. An imported photo capture is not a reconstructed room: configure reconstruction or import a separately reconstructed USDZ, then review metric scale, alignment and named collision assets in the Business room manager on that computer before explicitly deploying to Isaac. NuRec reconstruction is a separate runtime and is not installed automatically.

## macOS desktop (Apple Silicon and Intel)

Choose `macos-arm64` for Apple Silicon or `macos-x64` for Intel. Mount the DMG or extract the matching ZIP, read this README, then double-click `install-macos.command`. Install Python 3.12 or 3.13 from python.org first; no Node or local NVIDIA driver is needed. Setup downloads verified Electron (or reuses a matching local Electron cache after verifying its official checksum) and the Python runtime dependencies into a private environment; it does not bundle/install a Python distribution or Google Cloud CLI.

The default location is `~/Applications/RoboDE`. Open `~/Applications/RoboDE/RoboDE.app` after installation, or run its `start.sh`. In **Environment → NVIDIA Isaac Sim**, configure **GCP** or **Existing worker**. For GCP, install Google Cloud CLI and run `gcloud auth login` on this Mac. Credentials are configured on the machine and are never included in the installer. Existing installations may be updated by rerunning the installer with the same `--directory`.

Command-line options and read-only validation:

```sh
./install-macos.command --directory "$HOME/Applications/RoboDE"
./install-macos.command --check
```

macOS cannot run native Isaac Sim. It can connect to an RTX machine on your own network instead of GCP through **Existing worker**, with a secured connection. Installing RoboDE does not start or change a VM. Set idle shutdown and maximum runtime when configuring your GCP connection. Windows/Linux also support `--remote-isaac` to use remote Isaac instead of requiring a local RTX runtime; do not combine this with local Isaac installation options.

These are **unsigned bootstrap installers**, including the Mac disk images and generated `.app` launcher. The disk image contains setup files, not an offline drag-and-drop app. Follow your operating system’s security prompts for software you trust. No signing/notarization identity is configured in this project. A cached official Electron ZIP can also be supplied with `--electron-archive PATH`; checksum verification still requires the official release metadata. Windows native MSI/EXE and Linux AppImage installers are not produced by this build.

## Business App installation (computer and phone)

The **Server edition already serves the Business App** at `http://SERVER_IP:8080/business/`; configure HTTPS for use from a phone. Share the HTTPS Business App URL and workspace access code with your team. Keep the private API on loopback.

On a phone or computer, open that URL, sign in and choose **Install app**. Chrome/Edge can display an installation prompt when supported. iPhone/iPad: Safari → Share → Add to Home Screen. On macOS Safari: File → Add to Dock. The instructions remain available even when the browser does not offer a native prompt. Installed apps still need the RoboDE server for commands and planning; only the separate room capture page supports offline photo capture/export. No robot control or authenticated API responses are cached by a new service worker.

The `RoboDE-Business-0.4.0-all-platforms.zip` companion package contains `START-HERE.html` with installation instructions that need no Python. It also includes optional Python 3 desktop shortcut installers and the offline capture page:

```sh
# Linux (macOS may instead double-click install-business.command)
bash install-business.sh --url https://workspace.example.com
```

```powershell
.\install-business.ps1 --url https://workspace.example.com
```

These create a URL shortcut and copy the offline room capture page to `~/RoboDE-Business`; they do not create a second backend or copy project data. Remove that folder to uninstall the shortcut. For the installed browser app, use the browser/OS app uninstall controls. Save/export phone room captures before clearing browser storage.

## Build distributables

From the source checkout after `npm run setup`:

```sh
npm run installers:build
# On macOS, additionally create Apple Silicon + Intel disk images:
npm run installers:build -- --dmg
```

This builds both production frontends and writes **six Desktop/Server ZIPs, one Business companion ZIP, SHA-256 files, a release manifest and `START-HERE.html`** under `dist/releases/0.4.0-installers`. `--dmg` additionally builds two macOS disk images on a Mac. Previous release folders are preserved. The build uses an explicit source allowlist: saved user projects, runtime data, keys, provider credentials, logs and development node_modules are excluded. Each archive contains a payload checksum manifest. Electron is downloaded from the pinned official release and checked against its published SHA-256 when installing a desktop. These are bootstrap installers; dependencies need network access during setup. Windows/Linux packages require installation acceptance tests on their target operating systems; building an archive on macOS does not validate its NVIDIA runtime.

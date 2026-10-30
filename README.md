# RoboDE

RoboDE is a robotics IDE for setting up robots, building scenes and running task
plans. It runs in a browser or an Electron desktop window. Both use the same
React interface and Python backend, so projects and robot definitions work across
the two.

The built-in simulator and local task templates work without a GPU or an AI
account. Isaac Sim, hosted language models and physical robot drivers are optional
integrations that you configure separately.

## Run locally

You need **Node.js 22.12 or later** and **Python 3.11 or later**. Run these commands
from the repository root:

```sh
npm ci --ignore-scripts
npm run setup:server
npm run dev:web
```

Open [localhost:5173](http://127.0.0.1:5173). The setup command creates a Python
virtual environment in `.venv` and installs the backend dependencies. Stop the
development server with Ctrl+C.

For the desktop app, run `npm run setup` followed by `npm run dev` instead.
Desktop setup also downloads Electron. The browser and desktop launchers use the
same backend port, so stop one before starting the other.

## Try a plan

1. Open a sample project, such as **Apple transfer** or **Dual arm cell**.
2. Check the robot instances in **Robots** and their placement in **Environment**.
3. In **Plans**, create a plan and add tasks from a robot's command catalog, or
   enter an instruction and use **Generate plan**.
4. Review the tasks, robot assignments, parameters and dependencies. Choose
   **Validate plan**, then **Run simulation**.

The offline templates support a small set of pick/place and move-home requests.
For broader instructions, add a provider in **Configuration → AI Models** and
select the Planner and Converter models. Ollama, compatible hosted APIs and
reviewed custom adapters are supported. See [AI configuration](docs/LLM_ADAPTERS.md).

New robots are configured in **Configuration → Robot library**. Import a URDF,
review the joint and tool mappings, test the selected adapter and publish the
configuration before adding a project instance. The [robot setup guide](docs/ROBOT_LIBRARY.md)
and [URDF guide](docs/URDF_IMPORT.md) cover this in more detail. The in-app tutorial
walks through the main workspaces.

## Host the browser IDE

After the local dependency setup, build both frontends and start the server:

```sh
npm run server:build
npm run business:build
npm run server:start
```

Open `http://SERVER_IP:8081` and sign in with the team access code printed in the
terminal. Everyone using that code shares the same workspace. The calculation
API listens on loopback; the gateway serves the UI and authenticated API requests.
Use HTTPS for remote access and phone camera or microphone features.

The [server guide](SERVER_CLIENT/README.md) covers Windows/Linux deployment,
Docker, ports, access codes, persistent storage and backups. The separate
[Business App](BUSINESS_APP/README.md) provides a touch-oriented workspace and
phone room capture using the same backend.

## Repository layout

| Path | Contents |
| --- | --- |
| `SERVER_CLIENT/client/` | Shared React/TypeScript IDE, 3D viewport and Monaco editor |
| `SERVER_CLIENT/server/` | Python API, planning, validation, adapters and simulation |
| `SERVER_CLIENT/server/examples/` | Sample projects, robots, plans and API clients |
| `SERVER_CLIENT/deploy/` | Docker, HTTPS proxy and service configuration |
| `ELECTRON_APP/` | Desktop shell for the shared IDE |
| `BUSINESS_APP/` | Business frontend and gateway entry point |
| `workers/robotics/` | Optional Linux MoveIt/Nav2 worker |
| `installers/` | Desktop, server and Business companion package builders |
| `scripts/` | Development launchers, diagnostics and recording tools |
| `tests/` | Backend tests, adapter contracts and shared browser tests |
| `docs/` | Setup guides, architecture and dated validation reports |

Saved projects live in `SERVER_CLIENT/server/projects/`. Machine settings,
credentials, imported models and runtime state live in
`SERVER_CLIENT/server/robot_system/runtime/`. Both directories are private and
ignored by Git. A fresh checkout seeds its projects from the committed examples;
existing projects are preserved. Back up both private directories together.

Provider environment variables can be set in `SERVER_CLIENT/server/.env`; use
[`.env.example`](.env.example) as a starting point. Saved provider profiles are
also private runtime data. Build output, recordings and test artifacts stay out
of source control.

## Development checks

```sh
npm test                       # Python runtime and adapter tests
npm run typecheck              # Shared IDE TypeScript
npm run build                  # Shared IDE production build
npm run business:build         # Business App TypeScript and production build
npx playwright install chromium
npm run test:e2e               # Shared IDE browser workflows
npm run server:test            # Authenticated browser deployment
npm run business:test          # Business UI and phone capture
npm run electron:test          # Electron shell; requires desktop setup
```

Browser tests use disposable workspaces. Native robotics tests are opt-in and
require the Linux worker; see [local robotics setup](docs/ROBOTICS_V2_LOCAL.md).
For headless examples, use `npm run scenario -- --list` and
`npm run scenario -- --example apple_transfer`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and
[scripts/README.md](scripts/README.md) for the supporting tools.

## Simulation and hardware

The built-in preview uses kinematics and idealized grasps. It is useful for
testing a plan, but does not model contact physics or certify a real robot's path.
Native Isaac Sim requires a separately installed NVIDIA GPU runtime or a remote
worker. Physical execution requires a reviewed driver, measured feedback,
qualification and explicit arming. Passing a simulation does not qualify hardware.

See [Isaac Sim setup](docs/ISAAC_SIM.md), [robotics and physical execution](docs/ROBOTICS_V2_LOCAL.md)
and [recording](docs/SCENE_RECORDING.md) for the integration requirements and limits.
`npm run dev:nvidia` starts the NVIDIA edition with its first-boot setup; its
defaults are described in the [NVIDIA edition guide](docs/NVIDIA_EDITION.md).

## Documentation and packages

The [documentation index](docs/README.md) groups the guides and validation reports.
Start with the [architecture](docs/ARCHITECTURE.md) for the backend design or the
[project timeline](docs/PROJECT_TIMELINE.md) for implementation history.

Build installer packages with `npm run installers:build`; on macOS, add
`-- --dmg` for disk images. Requirements and supported targets are in the
[installer guide](installers/README.md). Generated packages belong in release
assets, outside the source tree committed to Git.

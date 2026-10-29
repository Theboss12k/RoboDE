# React IDE and local calculation server

The full IDE runs in a browser. The server owns the project files, robot registry, SQLite catalog, LLM credentials, planner, inverse kinematics, validation, scheduling, adapters and simulation. The browser performs UI/3D rendering and sends API requests to the same origin; it does not run the Python engine or need Electron/Python installed.

This deployment is a **shared team workspace**. All people who sign in with the team access code see the same projects. Resource ownership serializes conflicting robot/control work across browsers. The code is full IDE/operator access; the separate business gateway retains its limited API. The authoritative runtime must use one worker process because ownership and active sessions are held there.

```text
SERVER_CLIENT/
  client/               React/TypeScript IDE, Three.js, Monaco, tutorial
  server/
    services/           API, planning, IK, execution, LLM and adapter services
    shared/             Typed contracts and schemas
    robot_system/       Reusable models and private runtime state
    projects/           Project → Plans → Tasks, immutable revisions and runs
    simulation/         Built-in and optional native Isaac integration
    integrations/       ROS 2, GCP lifecycle and NuRec workers
    examples/           Runnable standardized task examples
    task_library/       Reusable task templates
    web/                Authenticated browser gateway
  deploy/               Docker, Compose, Linux service and HTTPS proxy examples
  tests/                Production browser-server tests
```

## Windows or Linux: start from PROJECT

Install Node.js 22.12+ and Python 3.11+. These commands work in PowerShell and a Linux shell:

```sh
npm ci --ignore-scripts
npm run setup:server
npm run server:build
npm run business:build
npm run server:start
```

Open `http://SERVER_IP:8081` from another computer, or `http://localhost:8081` on the server. The terminal prints a generated team access code. It is stored under `SERVER_CLIENT/server/robot_system/runtime/server/access.json`; keep that directory private to the service account. Linux mode bits are set on the file; on Windows, use the service account's filesystem ACLs. Set `ROBOT_IDE_ACCESS_CODE` (at least 12 characters) to provide your own code instead. Changing it and restarting logs everyone out.

Only the authenticated gateway listens on the network. The calculation API stays on `127.0.0.1:8765` and the browser uses relative `/api/...` calls through the gateway. `ROBOT_IDE_HOST` and `ROBOT_IDE_PORT` configure the browser listener; `ROBOT_IDE_RUNTIME_PORT` configures its private calculation port. `ROBOT_IDE_PYTHON` can point to an existing server Python environment. Defaults require no configuration.

`npm run setup:server` creates `.venv`, installs the backend, and skips downloading Electron. `uvloop` is omitted on Windows, which uses Python's supported event loop. The UI and API are the same implementations used by Electron; there is no second planner or copied frontend to keep in sync. Server rendering is not required: Vite builds React assets that the Python gateway serves to browsers.

For HTTPS, put the gateway behind your existing TLS proxy, or adapt `deploy/Caddyfile.example` to your hostname. HTTPS is needed for browser camera/microphone features and for sending the login over an untrusted network. No domain, external server or cloud VM is provisioned by these examples. Local templates and built-in simulation work without an LLM or cloud account. Any configured LLM/API, ROS bridge or Isaac worker is called from the server, so `127.0.0.1` in a connection profile refers to the server, not the user's browser computer.

Press Ctrl+C to stop, or use `npm run server:stop` from another terminal. `npm run server:status` checks the matching server instance before reporting/stopping it. A Linux service example is included; adjust the Node path, service account, checkout location and directory ownership before enabling it. On Windows, run the same npm command in the service account's PowerShell or through your existing service/task supervisor. Do not launch multiple independent runtime workers against the same robot devices or project data.

## Docker on a Linux server

From PROJECT:

```sh
docker compose -f SERVER_CLIENT/deploy/compose.yaml up --build -d
docker compose -f SERVER_CLIENT/deploy/compose.yaml logs robot-ide
```

The logs show the access code. The Compose file mounts the checkout's `server/projects` and `server/robot_system/runtime`, retaining existing project definitions, imported models/assets, connection profiles, revisions, runs and catalog across container restarts. Back up both directories together. They contain secrets; they are not built into the image. File permissions must let the container/service account read and write them. To stop:

```sh
docker compose -f SERVER_CLIENT/deploy/compose.yaml down
```

The image is the CPU planning/built-in simulation server. Native Isaac/NuRec need their GPU runtime and approved assets as documented in [GCP setup](../docs/GCP_ISAAC.md) and [business/NuRec setup](../docs/BUSINESS_APP.md); they are optional integrations. Existing cloud idle-shutdown safeguards are preserved. No GPU VM starts simply because someone opens the browser IDE.

## Development and validation

```sh
npm run server:dev       # Vite React UI on 5173, private calculation API on 8765
npm test                # backend and adapter contracts
npm run server:test     # authenticated production UI, two browsers, server execution, Monaco
npm run test:e2e        # full shared IDE workflow
npm run business:test   # business UI/phone capture regression checks
```

`server:dev` is local developer mode. Use `server:start` for browser access from other machines. The production frontend is `client/dist`; it has no API keys or provider credentials. The generated-code view uses bundled Monaco workers rather than a remote editor CDN.

## Existing-data relocation

The original root `projects/`, `robot_system/`, `services/`, `shared/`, `simulation/`, `integrations/`, `task_library/`, and `examples/` were moved into `server/`. Saved project and runtime files were backed up and hash-verified before/after the move; historical run/revision JSON was not rewritten. SQLite artifact references remain relative to the server data root. This checkout's backup and verification manifests are in `artifacts/before-restructure-*` (private and ignored by Git).

The repository directory `Robot_IDE` is PROJECT in this layout; it was not renamed, so the original checkout path remains valid. The Electron shell moved to `ELECTRON_APP`; the business app moved to `BUSINESS_APP`.

# RoboDE

A robotics IDE for browsers and Electron, organized into **Robots**, **Environment**, and **Plans**, with the hierarchy **Project → Plans → Tasks**. Configure reusable robots, build a simulated world, assign atomic tasks to robot instances, compile immutable revisions, and inspect observed results.

**Recording-enabled edition (package version 0.4.0):** native Isaac camera → MP4 recording, project video history and authenticated downloads in both IDE versions; preserved previous installers. See [Scene recording](docs/SCENE_RECORDING.md). Also includes shared-team React/server deployment, Windows/Linux launchers, preserved Electron shell, and separated product folders; simplified workspaces, adapter generation/review/testing, source-labeled manual controls, and an updated guided tutorial. The included arm is fictional. Custom SDK drafts remain test-only; ROS 2 live manual controls require a separate bridge, connection validation and explicit arming. Automatic plans remain simulation-only. Native Isaac GPU physics and physical hardware acceptance remain unverified on this Mac.

Native scene recording and an 18-task, two-robot simulation have now been demonstrated on a GCP NVIDIA L4 with Isaac Sim 6.2.0. See [the recorded demo and validation](docs/NVIDIA_SCENE_RECORDING_DEMO_20261029.md).

## Installers

Download packaged installers from the [RoboDE 0.4.0 release](https://github.com/Theboss12k/RoboDE/releases/tag/v0.4.0).

Downloadable Desktop (Windows/Linux/macOS), Server (Windows/Linux) and Business companion packages are built with `npm run installers:build`. On macOS add `-- --dmg` for disk images. See [installer setup, prerequisites and updates](installers/README.md). The generated catalog is `dist/releases/0.4.0-installers/START-HERE.html`.

## Browser IDE on a Windows/Linux server

The checkout is PROJECT, with three product folders:

```text
PROJECT/  (this Robot_IDE checkout)
├── SERVER_CLIENT/
│   ├── client/       React IDE and bundled Monaco editor
│   ├── server/       Planning, IK, validation, adapters, simulation and project data
│   └── deploy/       Docker, HTTPS proxy and service examples
├── BUSINESS_APP/     Business-facing React app and limited gateway
└── ELECTRON_APP/     Existing Electron desktop shell using the shared IDE
```

Install Node.js 22.12+ and Python 3.11+, then run from PROJECT (PowerShell or Linux shell):

```sh
npm ci --ignore-scripts
npm run setup:server
npm run server:build
npm run business:build
npm run server:start
```

Open `http://SERVER_IP:8081` in a browser and use the team access code printed by the server. The React frontend is served to the browser; the Python backend runs calculations on the server. All team members share the same projects and resource ownership. Python, Electron and robot SDKs are not required on browser computers. The private calculation API stays on the server's loopback interface. See [server deployment and data migration](SERVER_CLIENT/README.md) for HTTPS, configuration, Docker, persistent data and Windows/Linux instructions.

For the existing Electron version, run `npm run setup` once, then `npm run dev`, or `npm run build && npm run electron:start`. For local frontend development, use `npm run server:dev` and open `http://127.0.0.1:5173`. The shared server and a standalone Electron calculation runtime must not use the same port simultaneously; stop the running server first.

Electron now includes **Environment → Isaac Sim setup**: choose a **GCP GPU VM** for macOS or an installed **local Isaac Sim** on a supported Windows/Linux NVIDIA GPU host. Local setup includes native launcher selection, automatic project scene loading, optional manufacturer USD catalogs, worker Start/Stop, status and logs; GCP retains on-demand boot and idle-shutdown safeguards. See [desktop setup](ELECTRON_APP/README.md).

Saved workspaces under `SERVER_CLIENT/server/projects` and all machine runtime/credentials are excluded from Git. On first launch from a fresh source checkout, RoboDE copies the clean examples into that private project directory. Existing projects are preserved. Tests use the canonical examples directly.

## First workflow

1. In **Robots**, inspect a project instance and its saved initial joint configuration. Model limits/capabilities are shared across projects; saving initial joints does not move the robot.
2. In **Environment**, choose the built-in simulator or Isaac Sim. Switching automatically transfers robots, placements, current stopped joint positions, objects and imported static meshes; returning to built-in carries observed state back. Configure the GPU worker once. Reset applies saved starting configurations separately.
3. In **Plans**, select **New plan**, name it, and describe the goal. **Generate tasks from goals** expands supported instructions into atomic tasks with explicit robot assignments.
4. Review task parameters and dependencies, then **Compile plan**. Compilation creates an immutable revision with validation, motion samples, source and an exact configuration snapshot.
5. Select **Simulate**. View feedback and logs in Simulation; Stop requests cancellation and separately reports stopped confirmation. The timeline previews predictions without commanding robots.
6. Open **Generated code** or **Run history**. A recorded run reopens its exact revision. Editing configuration or tasks requires recompilation; history remains unchanged.

Robot adapter setup now starts with **Physical / Virtual → Vendor documentation / Custom commands**. Review the final command list and adapter, then test each command beside the robot in the automatically opened built-in simulator window. The included **Wave** example turns the demo arm right, left and back to centre. See [command setup and testing](docs/ADAPTERS.md).

Open **Configuration** in the top bar to import robot model definitions, add configured project instances, and manage multiple LLM adapter functions. Tasks select their own LLM for drafting/refinement or use an **LLM task** type to produce a recorded answer during execution. See [configuration and LLM functions](docs/CONFIGURATION.md).

Robot setup also supports **Import URDF** with packaged meshes, deterministic extraction, optional LLM metadata suggestions and explicit review of missing fields. See the [URDF import guide](docs/URDF_IMPORT.md) and [project timeline](docs/PROJECT_TIMELINE.md).

Use **Robot workspace** in Environment or Plans → Simulation to see sampled tool reach for one or all robots, with **Fit view** and world-space bounds. The overlay respects model joint limits and placement; collision-free paths and tool orientation still require planning checks.

Environment edits now preview immediately. **Import 3D object** loads GLB, embedded glTF, OBJ and STL in the built-in simulator; **Save scene** retains the geometry and placement. See [scene assets](docs/SCENE_ASSETS.md).

For two robots, choose **Dual arm cell**, create a plan, generate tasks from its two default robot goals, compile and simulate. Independent work overlaps; shared robots, objects and destination regions serialize. Add project instances in Robots, and place their bases in Environment.

The gripper uses metres and angular joints use radians. Instance YAML declares per-actuator units explicitly.

## Tutorial and adapter controls

**Tutorial** is available in the title bar and navigation rail anytime. The guide covers all three workspaces, atomic task editing, the six adapter setup stages, manual controls and run history. It has smooth spotlights, section jumps, keyboard navigation, reduced-motion support and view/focus restoration. During execution it exposes Stop simulation.

Open **Robots → Adapters & controls → Generate adapter** for templates or an AI-assisted SDK draft. Robot SDK is the first Physical choice; ROS 2 is an alternative. Virtual choices are the built-in simulator and Isaac Sim. Review generated code, run simulated transport contract tests, then open the adapter's **Controls** panel. Isolated simulated testing is the default. SDK draft source is not executed. Each physical instance can select and edit its own connection profiles.

Connected simulator controls hold the same cell ownership as plans. ROS physical manual controls require reviewed/tested content, fresh feedback, validated connection/stop and explicit arming. Real hardware acceptance is still required. See [adapter generation and ROS setup](docs/ADAPTERS.md).

For native physics, follow [Isaac Sim setup](docs/ISAAC_SIM.md), configure `ISAAC_WORKER_URL` / `ISAAC_WORKER_TOKEN`, and select Isaac Sim in Environment. Connecting reads state; explicit reset initializes the scene.

## AI providers

The default **Local templates** provider works offline and accepts a deliberately narrow pick/place or move-home grammar. Unsupported, compound, conditional, throwing, catching, or ambiguous requests fail explicitly. There is no implicit fallback from an unsupported task to an easier operation.

For an inference provider, open **Configuration → LLM adapters**, add a compatible API root/model and credentials, then test and select it. Multiple profiles and per-task selection are supported. Legacy environment configuration is also supported: copy `.env.example` to `SERVER_CLIENT/server/.env`, set `AI_BASE_URL` (the API prefix before `/chat/completions`), `AI_MODEL`, and `AI_API_KEY`, then restart. Choose an endpoint/model supported by the actual provider. No NVIDIA or Nebius account is assumed or bundled.

Configured LLMs propose schema-valid tasks using the selected robot’s command contract and observed world. Offline templates produce the same standardized task records. Direct actuator/component commands bypass IK; end-effector poses use the configured solver. The compiler calculates and validates motion before simulation. A separate SDK drafting request can propose reviewable source from supplied documentation; this source is never automatically imported or executed. Template-based generation remains available offline.

## Layout and persistence

| Location | Responsibility |
| --- | --- |
| `SERVER_CLIENT/client` | Shared React IDE, Three.js viewport, React Flow task graph, local Monaco editor |
| `ELECTRON_APP` | Sandboxed desktop shell for the shared React frontend |
| `BUSINESS_APP` | Business UI, touch workspace, voice input and room capture |
| `SERVER_CLIENT/server/services/ai_orchestrator` | Provider-independent intent contract and local/compatible providers |
| `SERVER_CLIENT/server/services/task_engine` | Dependency ordering and explicit lifecycle transitions |
| `SERVER_CLIENT/server/services/planning` | Analytic/serial-chain FK/IK, standardized task templates and quintic sampled trajectories |
| `SERVER_CLIENT/server/services/validation` | JSON schemas, semantic BOT checks and sampled motion checks |
| `SERVER_CLIENT/server/services/execution` | Shared resource ownership, simulation feedback, cancellation and verification |
| `SERVER_CLIENT/server/services/adapters` | Generated bundles, review/testing, connection profiles and manual control sessions |
| `SERVER_CLIENT/server/integrations/ros2` | Optional authenticated ROS-enabled controller bridge |
| `SERVER_CLIENT/server/services/world_model` | Scene objects and geometric postconditions |
| `SERVER_CLIENT/server/robot_system/registry/models/demo_arm` | BOT files, local control schemes, adapter declarations and implementation |
| `SERVER_CLIENT/server/projects/<id>` | Project, instance configuration, world, plan definitions/revisions and results |
| `SERVER_CLIENT/server/robot_system/runtime` | SQLite run index and separately persisted simulation state |
| `SERVER_CLIENT/server/shared` | Typed contracts, schemas, adapter interface |
| `SERVER_CLIENT/server/simulation/scenario_runner` | Reproducible headless local preview |

Each plan saves an editable `plans/<plan>/definition.json`. Compiled revisions save `plan.json`, `snapshot.json` and `generated.py` under `plans/<plan>/revisions/<revision>/`. Runs save result JSON, logs, lifecycle and evidence, indexed by SQLite. Definition versions and SHA-256 configuration/state fingerprints reject stale execution. Legacy task artifacts are copied into this hierarchy with backups; originals and historical results are preserved.

Projects support up to eight demo-arm instances. The compiler schedules independent atomic tasks concurrently and serializes shared resources. The analytic solver remains specific to the demo geometry; serial-chain pose examples include an explicit kinematic model. A generated adapter alone does not supply another manufacturer's kinematics or validated driver.

Runtime feedback is separate from saved initial state. The preview restores its last persisted scene on restart. An unfinished run is marked failed with completion/stop unverified; it is never silently resumed or reported successful. Reset the preview before retrying an interrupted grasp.

## Verification

```sh
npm test                    # isolated runtime, BOT, adapter and failure tests
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e             # browser workflow, code view, cancellation, configuration
npm run scenario -- --list
npm run scenario -- --example apple_transfer
npm run scenario -- --example multi_robot
npm run scenario -- --example multi_effector_pose
```

The scenario runner uses isolated curated project copies and exports definitions, immutable revisions and run artifacts under `artifacts/examples/`; it can run while the desktop is open. All nine source examples use the new convention. See [runnable examples and API clients](examples/README.md). Python tests use temporary projects. Browser tests create and remove their own project directories.

The current validator samples joint limits, velocity/acceleration, table clearance, link/box proximity and carried-object/box collisions. Local preview does **not** implement contact/grasp dynamics. The native Isaac worker uses USD/PhysX dynamics and measured object poses, but those physics runs still need GPU acceptance. Neither simulation path provides a continuous collision/self-collision certificate, perception uncertainty handling, MoveIt, hardware safety certification, or throwing/catching. ROS 2 manual transport is a separate optional bridge with its own deployment acceptance.

See [implementation status](docs/ROADMAP.md), [architecture](docs/ARCHITECTURE.md), [Isaac Sim integration requirements](docs/ISAAC_SIM.md), and the [original specification](docs/SPECIFICATION.md).

### Capability-based tasks and remote Isaac

**Task type → Robot command task** supports direct actuator/component targets and named end-effector pose targets. Only pose tasks invoke configured IK. With a selected LLM adapter, the goal assistant now decomposes goals using the robot's command contract and observed world state. See [task generation and system prompts](docs/TASK_PIPELINE.md).

**Environment → Isaac Sim setup → GCP GPU VM** saves an authenticated tunneled endpoint. Managed workers load approved robot USD assets per project instance, expose native manual controls, and apply box object add/remove edits. See the [GCP setup walkthrough](docs/GCP_ISAAC.md). Native GPU validation remains separate from automated desktop/transport checks.

## Business workspace and phone capture

The separate `BUSINESS_APP` app provides named workspace assets, touch navigation, reviewed natural-language commands, voice input and room photography. Run `npm run business:build` and `npm run business:phone` for protected temporary HTTPS phone access. See [business app and NuRec setup](docs/BUSINESS_APP.md) and [on-demand GCP GPU shutdown safeguards](docs/GCP_ISAAC.md).

Cloud access and on-demand operation: [Cloud IDE and Business App](docs/CLOUD_APP.md).

RTX server and local desktop installers: [installer guide](installers/README.md). Build clean Windows/Ubuntu installer ZIPs with `npm run installers:build`.

Global robot setup: **Configuration → Robot library → Add robot to library**. Import/review the definition, select or create a compatible physical/virtual control adapter, then test in isolation. In **Robots**, add a project instance by choosing the global robot and adapter; the pairing persists with the project.

Detailed guides: [global robot setup](docs/ROBOT_LIBRARY.md) · [28 October release validation](docs/RELEASE_20261028.md).

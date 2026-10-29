# RoboDE project timeline, feature updates and bug-fix history

Updated **29 October 2026, India time**. Product formerly called **Robot IDE / Robot_IDE**; the business frontend is now **RoboDE Workspace**.

This file consolidates the provided chat, the current implementation, and retained validation reports. It follows the conversation's order for undated work and uses calendar dates only where a dated report or explicit chat evidence exists. It omits passwords, tokens, private access codes and private deployment URLs.

## Version and evidence conventions

The checkout's root, shared IDE, Business App and Electron packages now use **0.4.0**, the recording-enabled edition introduced on 29 October 2026. The preceding verified package baseline was **0.3.0**. No committed release history is available in this checkout. Earlier milestones below are development phases within the 0.3.0 lineage, **not invented 0.1/0.2 releases**. Repeated dated entries describe successive builds/validation snapshots of 0.3.0. An older README labelled the server restructure “Release 0.4” without matching package versions; its heading has been reconciled to the current manifest version rather than treating it as a verified published release.

- **Implemented**: behavior exists in the current source, with its scope noted.
- **Validated then**: retained reports record a test at that point; it is not a claim that a cloud VM or hardware is running now.
- **Explained**: a question was answered without a corresponding code change.
- **Remaining**: requested or discussed capability still needs external setup, validation or additional implementation.
- Test counts below are historical snapshots, not additive totals. The latest full backend result supersedes earlier counts.

## Overview by application

| Application | Current role | Relevant milestones |
| --- | --- | --- |
| Local Electron IDE | Shared technical React IDE in a sandboxed desktop shell; local backend; configurable GCP Isaac on macOS or local Isaac on a supported Windows/Linux GPU host | Initial IDE; robot/task redesign; controls; native file selection; global library; local installers; welcome/branding; URDF import |
| Server/browser IDE | Shared-team workspace served to a browser; planning, IK, execution, storage, LLM calls and resource ownership run on one backend | Folder restructuring; authenticated gateway; local Monaco; cloud deployment; hosted installers; same global robot/URDF flow |
| Business App / RoboDE Workspace | Limited, touch-oriented view of a configured project, named assets, reviewed commands, voice input and room capture | Separate business subproject; phone HTTPS access; contextual feedback; unified palette/branding; offline capture/export |

The Business App consumes configured robots; engineering robot imports and adapter authoring belong in the IDE. Automatic robot plans remain simulation-based. Physical adapters add separately guarded manual control, not automatic hardware authorization.

## Undated early development, in chat order

### P01 — Initial IDE and simulator foundations

**Request:** Build the supplied Robot_IDE specification incrementally, then add Isaac Sim and multi-robot execution.

**Implemented:** Reusable robot definitions, project instances, a built-in kinematic simulator, a separate Isaac worker interface, task planning/validation, execution lifecycle, logs and persisted results. Multi-robot projects support synchronized state and explicitly assigned work.

**Later validation:** Runtime, scene and multi-robot tests are recorded in the dated reports below. Native physics acceptance was separate from early mock/contract tests.

### P02 — Always-available guided tutorial

**Request:** A Tutorial button available anytime, explaining screen elements with smooth transitions.

**Implemented:** Workspace/inspector guidance, section jumps, next/back, keyboard navigation, focus management, reduced-motion support, view restoration and an execution Stop entry while the tutorial is open.

**Scope:** Later tutorial revisions follow the simplified hierarchy, adapter setup, controls and URDF import.

### P03 — Project → Plans → Tasks and three workspaces

**Request:** Separate reusable robots, simulator/environment controls and task-specific assignment; remove confusing overlap between single-task and workflow authoring.

**Implemented:**

- **Robots:** global model references, configured project instances, joint settings, physical/virtual adapter selection and tests.
- **Environment:** built-in/Isaac selection, worker connection/reset, named scene objects, obstacles, regions, meshes and robot placement.
- **Plans:** expandable Project → Plans → Tasks tree; named goals, editable atomic tasks, explicit robot assignments, parameters, dependencies, validation, generated source and run history.
- Stable editable plan/task definitions; immutable compiled revisions; runs reference the exact revision.
- Repeatable legacy migration with backups, retaining dependencies, assignments, generated artifacts and historical results.
- Configuration/definition fingerprints reject stale execution and require recompilation without rewriting history.
- Independent tasks run concurrently; shared robots, objects and destination resources serialize.

**Bug/confusion resolved:** Selecting a robot elsewhere no longer implicitly reassigns existing tasks. Overlapping authoring surfaces were replaced with a single plan/task flow.

### P04 — Adapter generation, physical/virtual categories and controls

**Request:** Every generated adapter should have controls; support SDK/ROS physical targets and built-in/Isaac virtual targets.

**Implemented:** Reviewed generation drafts, metadata/provenance, mappings and units, injectable simulated transport, bounded commands, transport contract tests, separate adapter workers, supported joint/gripper/feedback/Stop controls and connection profiles.

Physical tests exercise command translation through simulated transport. Live manual control requires supported reviewed/tested content, a validated connection, fresh feedback and explicit time-limited arming. Disconnects/session changes clear arming. Resource ownership covers manual controls and plan execution, including connections identifying the same physical device.

ROS 2 uses a separate ROS-enabled bridge and monitored FollowJointTrajectory action handling. Stop requested and stopped confirmed remain separate states. Custom SDK drafts stay test-only until their actual integration is implemented and validated.

### P05 — Environment objects and 3D assets

**Reported bug:** Adding an object did not appear in the environment.

**Fix:** Draft scene objects render immediately; **Save scene** persists them. Previewed changes are distinguishable from saved state.

**Feature:** Import GLB, embedded glTF, OBJ and STL; choose scene role, source up-axis and metric size. Preserve geometry/placement on save and reload. External or unsupported asset references are rejected or explicitly reported instead of showing a false successful import.

**Evidence:** [Scene assets guide](SCENE_ASSETS.md), mesh/browser and scene-asset tests, later dated QA reports.

### P06 — Global LLM adapters and robot-model configuration

**Request:** Configure robot instances and import new robot definitions; provide multiple global LLM adapter functions selected per task for both drafting and standalone LLM work.

**Implemented:** Model bundle import/export; multiple named LLM endpoints/models/credentials; a global default; per-goal/per-task selection; task refinement; standalone LLM tasks; dependency-based answer references and immutable answer history. Credentials are excluded from public snapshots and generated artifacts.

**Explained in chat:** How to assign tasks; what postconditions, required capabilities, object/target IDs and success conditions mean; how a high-level goal expands into atomic tasks.

### P07 — Target-first adapter setup and standardized task pipeline

**Request:** Select physical/virtual target first, then vendor documentation or custom commands, generate/review the final command list and test each command. Rename user-facing “actions” to “tasks.”

**Implemented:** Target → method → command configuration → generate → review → simulator test wizard; custom command recipes and parameter validation; documentation-driven command discovery; source review, test reports and simulated feedback.

The standardized pipeline distinguishes direct actuator/component tasks from end-effector pose tasks. Explicit target IDs, units and ranges are validated. Direct commands bypass IK; pose commands use the configured solver, frames and limits. Unknown targets and unreachable poses fail explicitly. Serial-chain FK/IK supports configured non-demo chains, while grasp/contact support remains separately constrained.

**Examples:** Rewritten around plan definitions and standardized tasks; nine plan examples, API/CLI clients and a two-tool model example are described in [examples](../SERVER_CLIENT/server/examples/README.md) and [task pipeline](TASK_PIPELINE.md).

### P08 — GCP Isaac setup and credit controls

**Request:** Create a GPU VM, load/control robots in Isaac, edit scene objects and shut down when idle.

**Operational sequence recorded in chat:**

1. New account/project setup guidance, billing/quota prerequisites and Compute Engine API enablement.
2. Project ID supplied: `nvdiavm`.
3. GPU quota UI clarified; a free-trial restriction and quota/request process were discussed.
4. `asia-south1-a` VM creation failed with L4 resource-pool exhaustion. Retrying `asia-south1-c` succeeded; this was a capacity workaround, not a code fix or a quota guarantee.
5. A 200 GB boot disk warning was investigated. The guest showed a 193 GB root filesystem, confirming automatic expansion; no manual repartition was required.
6. Missing `nvidia-smi` exposed an uninstalled driver. Later user output confirmed NVIDIA L4 detection with driver 595.99.02.
7. Native worker/Isaac setup and authenticated SSH/OS Login integration followed. Secrets are not reproduced here.

**Implemented lifecycle controls:** On-demand start, activity tracking, explicit status/error reporting, an independent idle shutdown guard and provider maximum-run STOP policy. Visiting setup alone does not start the VM. Retained disks may remain billable while compute is stopped.

**Later deployment/acceptance:** See the dated 27/28 October entries; both VMs were subsequently left stopped.

### P09 — Darker professional UI, placement and live previews

**Request:** Darker styling, drag/rotate arrows, clickable robots, a second 3D model for joint/end-effector selection, commit/revert of a new starting environment.

**Implemented:** Dark technical workspace; enlarged translation/rotation controls; mesh/label picking; draft base translation/yaw; companion robot inspector; joint and tool controls; Revert and Use as starting point.

**Reported bugs:** Control arrows were too small; movement was not reflected in the environment; later movement only appeared after an interaction completed.

**Fixes:** Larger handles and buttons; adapter feedback drives both models; continuous controls update while dragging; intermediate connected feedback is polled; rapid targets coalesce; Stop/Revert clears queued movement and ignores late responses.

### P10 — Business App, phone use, voice and room capture

**Request:** A separate business frontend using the shared engine, named environment assets, natural-language commands, touch controls, speech-to-text, and a separate room-to-Isaac reconstruction feature.

**Implemented:** Business subproject; project/workspace selection; named asset list/search, 3D and floor-plan views; editable command drafts, review before simulation, results and shared feedback; guided asset choices; speech-to-text with permission/error handling.

Phone room capture stores overlapping photographs, supports uploads and releases camera tracks when closed or navigated away. A separate NuRec service contract, imported USDZ alignment, metric scale, named collision proxies and explicit deployment controls were added. HTTPS phone access was configured; later offline export/manual IDE upload supports local desktops.

**Remaining:** Real room GPU NuRec reconstruction/training is a separately configured runtime and was not completed by the recorded validation. Capturing photos alone does not infer a measured room or certify its collisions.

### P11 — NVIDIA branding and Monaco

**Request:** NVIDIA marks on NVIDIA-specific integrations; replace the embedded editor with Monaco if necessary; fix logo alignment.

**Implemented/fixed:** Locally bundled Monaco for generated Python and later custom LLM code. NVIDIA marks identify Isaac Sim/NuRec; logo/label centering and duplicate wordmark text were corrected. The supplied robot emblem was applied across desktop, browser, Business App, login and welcome surfaces in theme-appropriate colors.

### P12 — Server/client architecture and local/GCP deployment options

**Request:** React web IDE with processing on a Windows/Linux server, shared-team workspace, and separate `SERVER_CLIENT`, `BUSINESS_APP`, `ELECTRON_APP` folders. Retain configurable GCP Isaac on macOS; allow local Isaac on a supported RTX host.

**Implemented:** One private planning/runtime authority, authenticated same-origin browser gateways, shared persistent workspace, separate limited Business API surface, shared React IDE in Electron, platform-aware launch/configuration and scoped native file pickers. The browser performs interaction/rendering; planning, IK, execution and provider calls run on the backend.

**Fixes later validated:** Relocation model-loading race, LAN HTTP UUID fallback, test isolation/teardown conflicts and preservation of the active launch record after a rejected duplicate server start.

### P13 — Unified simulator selection and synchronization

**Request:** Switching between built-in and Isaac should transfer the scene automatically and keep settings/state consistent.

**Implemented/fixed:** Two-way managed-worker handoff of project robot set, placements, stopped current joints, named objects and supported static mesh assets. Unsaved scene drafts are included on a switch. Returning to built-in uses observed Isaac state. Explicit reset applies saved starting configurations separately.

**Boundaries:** Manufacturer assets need an approved matching USD articulation/catalog. Missing assets fail explicitly. Fixed manifest workers remain attach-only. Ownership transfer is atomic; destination claims, active motion or conflicting resources reject a switch rather than losing the current authority.

### P14 — Cloud app functionality and global library correction

**Reported problems:** The cloud app needed real end-to-end operation; global configuration was confusing and did not reliably add reusable robots to a global library.

**Implemented/fixed:** Global robot/adapter setup independent of projects; explicit persistent instance bindings combining a global robot and compatible adapter; isolated global tests; clean physical/virtual separation. Shared definition edits use writable data copies, registry deduplication and initial-state validation. Native cloud acceptance and persistence were later recorded on the L4 VM.

### P15 — RTX installers and offline mobile handoff

**Request:** Hosted server installer serving both React apps; fully local RTX Electron installer; retain macOS/GCP behavior; manually upload mobile captures to local desktops.

**Implemented:** Four clean bootstrap ZIP installers: server/desktop × Linux/Windows x64; preflight checks, data/application separation, checksum verification, optional Isaac setup and pinned Electron download. Offline phone capture exports a portable ZIP; the IDE imports captures or USDZ without changing the active scene.

**Scope:** Bootstrap ZIPs, not signed MSI/AppImage packages. Native Windows execution and arbitrary RTX compatibility still require target-host validation. Details are in the dated 28 October release below.

### P16 — UI audit, greeting, real LLM tests and recordings

**Request:** Test all editions, keep warnings visible beside the clicked controls, unify alignment/colors; animated Hello greeting; actual local Phi-4 functionality tests; detailed videos, with Business features but no live demo.

**Implemented/fixed:** Shared in-flow feedback, scoped dialog/camera errors, consistent severity colors, touch targets and dark login; boot/reload greeting with focus containment/reduced motion; later brand rename and tagline. Actual Ollama functionality results and narrated recordings are in the dated entries below.

### P17 — RoboDE branding, custom LLM code and discoverable IDs

**Request:** Align the IDE name beside its logo, rename it **RoboDE**, add **“Plan, control and command your robot.”**, hide prompt fields, permit standard adapter code or form setup, and explain where IDs are found.

**Implemented:** Wordmark baseline/spacing; shared tagline and document/login names; selectable Project ID below the explorer selector with copy/fallback; UI or Monaco Python LLM setup, import/download/sample and saved-function test. Internal prompt fields were removed from configuration/test/task inspectors; private provider prefixes survive UI edits but are excluded from public provider data/snapshots. New compiled source manifests omit legacy task prompt fields; historical revisions stay unchanged.

Trusted custom LLM functions run in separate timeout/cancellation-aware workers, with selected configuration/credentials and generic error handling. This is process isolation, not an arbitrary-code security sandbox.

**Explained:** The LLM adapter connects providers for drafting, SDK assistance and standalone text tasks; it is separate from the robot control adapter. Local Ollama uses the exact installed model name `phi4:14b` and backend-reachable `http://127.0.0.1:11434/v1`. `.robot.json` is RoboDE's reusable declarative model bundle.

## Dated validation and delivery timeline — package version 0.3.0

### 24 October 2026 — Shared server/browser edition

[Server validation report](SERVER_VALIDATION.md): three-application folder restructure, shared React/Python runtime, authenticated team gateway, server-side calculations, locally served Monaco and Linux production image. Reported checks: **172 backend**, **24 IDE scenarios across runs**, three Business browser scenarios and two authenticated server scenarios; original **146 saved project files unchanged**. Linux ARM64 initially had three optional-USD skips.

The Electron local/GCP follow-up raised backend coverage to **178**, added five hosted setup checks and verified scoped native file selection/sandboxing. Local Isaac on macOS is explicitly unavailable; Windows/Linux launch configuration remains supported with target-host GPU acceptance required.

### 25 October 2026 — Continuous controls and scene handoff

[Server validation follow-up](SERVER_VALIDATION.md#continuous-controls-and-simulator-hand-off--25-october-2026): **187 runtime tests**, then five targeted regressions for **192 distinct runtime cases**; **12 hosted browser scenarios**. Held-pointer movement, delayed/coalesced commands, Stop/Revert cleanup, automatic tool IK, intermediate feedback and two-way multi-robot transfer passed.

An ownership correction prevents another cell/device claimant from acquiring a destination during simulator handoff. GLB/glTF/OBJ/STL transfer gained explicit static-geometry conversion checks. Contract workers are labelled and production refuses to treat a non-physics fixture as native Isaac acceptance. No GPU VM was started in this pass.

### 27 October 2026 — Cross-edition QA and contextual warnings

[QA report](QA_20261027.md): **196 backend tests on macOS and Linux ARM64**, **49 UI scenarios** across shared IDE, hosted IDE, Electron and Business App. Linux production frontend/backend execution and shared feedback passed. Original **146 project files unchanged**.

Fixes included in-flow feedback, dialog/camera scoping, GPU start-result polling, explicit capacity errors/retry, dark shared login, rejected-code explanation, common UI palette, readable map labels, ≥44 px Business controls, NVIDIA centering, isolated browser fixtures and duplicate-launch state protection.

Fresh native GCP acceptance was initially **blocked** after repeated L4 stockouts in `asia-south1-c`. That report's blocked status is historical; the later cloud acceptance below records the separate recovery/deployment.

### 27 October 2026 — Later native cloud deployment and physics acceptance

[Cloud validation](CLOUD_VALIDATION_20261027.md), [deployment status](GCP_DEPLOYMENT_STATUS.md): recovered the cloud deployment onto `robot-ide-isaac-cloud` in `asia-south1-b`, retaining the stopped original VM in `asia-south1-c` as rollback. One persistent Linux backend serves both authenticated apps; a separate Isaac Sim 6.2.0 worker runs native physics.

Reported checks: **201 runtime**, eight Business browser, two Electron; public cloud login/Monaco/controls/named USD inventory; native two-robot concurrency; object CRUD and mesh transfer; public phone-sized nine-task Apple transfer verified against observed native poses; persistent project/history storage and boot-enabled services. The guest guard remained **600 seconds** and provider STOP cap **7200 seconds**.

Native tests corrected the educational gripper proxy's aperture mapping, fingertip clearance and forearm overlap. Apple primitives now agree across browser/native shape; bounded velocity feedforward improves force-driven tracking. Contact verification allows the authored contact offsets/solver slop while raw joint-limit checks remain strict. Failed contact runs were reported and retained, not relabelled as passes.

This was educational asset/native-physics acceptance, not arbitrary manufacturer/hardware certification or native Isaac-editor video streaming. NuRec GPU training was not installed.

### 28 October 2026 — Global library and four RTX installer bundles

[Release report](RELEASE_20261028.md): global robots/adapters independent of projects, reviewed/tested binding hashes, persistent project pairings, writable bundled-model copies, initial-state/limit validation, and safe wizard closure. Offline mobile ZIP/USDZ import added.

Reported checks: **210 runtime**, five installer-specific tests, 25 IDE browser, 16 hosted, nine Business and two Electron; production builds passed. The actual L4 VM validated a separate Linux installer and concurrent native two-robot plan using its existing Isaac environment. Official Electron checksum/extraction and all four installer payload hashes passed; private data/credentials excluded.

The installer fixes preserve virtual-environment executable paths and accept the official checksum manifest's `*filename` notation. Native Windows installation, graphical Linux/Windows desktop operation and a fresh full NVIDIA package installation were not certified by this test.

Both GCP VMs were left **stopped** after maintenance; idle/max-runtime safeguards remained configured. Stopped retained disks still have storage costs.

### 29 October 2026 — Welcome and final UI review

[UI review](UI_REVIEW_20261029.md): shared animated Hello on boot/reload, early dismissal, accessible naming, inert content during greeting, focus return and reduced motion. Business NuRec contrast/progress styles improved; floor-plan asset locations now follow the same observed feedback as the 3D view.

**55 distinct UI checks** passed across IDE, hosted, Business/mobile and actual macOS Electron; both builds passed and installer bundles were rebuilt. A welcome accessible-name spacing issue, phone timing and polling teardown synchronization were fixed. No fresh GPU acceptance or remote redeployment was claimed for this UI pass.

### 29 October 2026 — Real Ollama Phi-4 functionality and validation fixes

[Ollama report](OLLAMA_FUNCTIONAL_TEST_20261029.md): actual installed **`phi4:14b`**, 46 recorded provider requests, **9/10 final scenarios passed**, **47 focused regressions passed**. Browser and Electron SDK drafting/testing and simple command planning passed; Business commands, virtual generation, Cartesian IK and unknown/unreachable rejection passed.

The final compound apple-lift scenario **failed safely**: the proposed grasp was above the object. An earlier attempt worked, so this was explicitly reported as unreliable rather than a general planning certification.

Fixes: single fenced JSON/Python response handling with validation, stricter SDK injected-transport instructions and honest unimplemented vendor methods, compact per-command schema, one bounded formatting repair, observed-state grounding of relative vertical lifts, and independent compiled final-position/held-state checks before saving/preparing requests. Semantic errors are not silently replaced or clamped. No GCP VM was booted for these LLM checks.

### 29 October 2026 — RoboDE name, code-based LLM adapters and three videos

[Branding/recording report](ROBODE_UI_AND_RECORDINGS_20261029.md), [video index](../artifacts/walkthroughs/README.md): aligned RoboDE name, shared tagline, visible/copyable project IDs, form/Python LLM setup and hidden prompt fields. **40 backend integration** and **12 UI/Electron checks** passed for the scoped changes; both production builds passed.

Three genuine UI walkthroughs were edited with narration, captions and chapters: native Electron **8:53**, server/browser IDE **8:56**, Business desktop/phone features **3:11**. IDE footage includes actual Ollama invocation/task drafting, adapter review/test, scene editing, motion, history, direct commands, Stop and multi-robot execution. The reused SDK draft is labelled as generated in the earlier Phi-4 test.

Business footage submitted **zero commands**, ran **zero simulations**, recorded **zero photos** and did not activate camera/microphone/reconstruction. Isaac footage shows setup and an unavailable worker, not a fresh GPU run. Both GCP VMs were verified stopped. The normal local app was restored after isolated recording services were stopped.

### 29 October 2026 — Current delivery: reviewed URDF import with LLM assistance

**Request:** Implement the preceding URDF conversion proposal, then consolidate the entire chat into this timeline.

**Implemented in Electron and shared server/browser IDE:**

- Import expanded `.urdf` or URDF/mesh ZIP, with optional path selection for multi-model archives.
- Deterministic extraction of identity, link/joint tree, origins, axes, units and authored limits. Read-only extracted mechanical fields cannot be overwritten by LLM suggestions or the review API.
- Explicit configuration for absent acceleration/limits, reviewed initial positions, tool-link selection, optional verified payload and gripper endpoints. Unknown payload remains labelled unrated; continuous joints require a finite control window.
- General negative/oblique axis vectors in server FK/IK, schema and browser preview; exact frame transforms retained. Unsupported mimic/coupled, planar and floating joints block import explicitly.
- Selected global LLM adapter can propose metadata/tool labels and advisory capability/command mappings. Quotes must support manufacturer/command claims. Suggestions require explicit acceptance and cannot activate skills, hardware or change geometry/limits. Manual conversion works without an LLM.
- Validation outside the active registry, explicit review acknowledgment and atomic registration into the existing global library. Then the normal physical/virtual adapter selection and isolated test flow continues.
- Source/mesh retention, hashes, review/LLM provenance and original source download. Missing meshes are visible warnings; original mesh physics and native USD conversion still need separate Isaac setup.
- Bounded uploads/archives; no external mesh downloads, XML DTD/entities/includes, xacro execution, plugin loading, traversal paths, symlinks or duplicate archive entries.
- Updated tutorial, import/configuration documentation and a fictional gantry example.

**Integration bugs found and fixed during this delivery:**

1. Global template test windows displayed feedback without joint/tool controls. Library-scoped tests now expose bounded simulated controls and the 3D preview while remaining incapable of live arming/hardware connection.
2. Cartesian Move compilation assumed a `gripper` actuator, causing a non-gripper robot failure. Generic robots now compile and execute supported pose moves without that assumption.
3. Coincident anchored root/fixed frames were mistaken for arm links crossing the floor. Serial-chain floor checks skip frames coincident with the anchored root, while checking actual nonzero arm segments/points. A ground-level arm away from its root is still rejected.
4. Negative/non-cardinal axes could not be expressed consistently by the previous cardinal-axis-only preview. Axis vectors now drive both IK/FK and rendering.

**Current verification:** full backend suite **258 passed**, including retained source/restart, atomic import, malicious/unsupported inputs, advisory LLM validation, oblique FK, negative-axis tool IK and an executed non-gripper Cartesian plan. The final targeted URDF suite **23 passed**, including one additional non-root floor regression. Full shared IDE browser suite **30 passed**, hosted browser **18 passed**, native macOS Electron **3 passed**, Business browser **10 passed**, and installer unit tests **5 passed**. Both production builds passed; all four installer archives were rebuilt and their payload/checksums verified. Real local Ollama `phi4:14b` returned metadata suggestions without changing mechanical values. Final scope/results are recorded in [URDF delivery validation](URDF_VALIDATION_20261029.md). These separate suite counts are not additive.

No cloud VM, real robot, NuRec reconstruction or native URDF-to-USD GPU validation is required or claimed for this change. The Business App continues to consume project-configured robots rather than exposing the import wizard.

### 29 October 2026 — Shared IDE visual overhaul and verified restart

**Request:** Overhaul the UI, align components, add appropriate hover feedback, verify buttons and restart desktop/web.

**Implemented:** A unified desktop/browser workspace skin with readable typography, consistent cards/fields/buttons, clearer selected navigation, workspace counts, aligned chrome/inspectors, compact toolbar wrapping, focus/hover/pressed states and reduced-motion support. Secondary room import moved into the environment tools. Disabled plan controls explain their prerequisites.

**Behavior fix:** Clicking the modal backdrop could bypass Configuration's busy/session guard. Backdrop/Escape now use the current dialog's permitted close action. Dialogs contain keyboard focus and return it to their opener; pending create submissions cannot be dismissed through their close button.

**Verification:** Full shared IDE browser suite **30 passed**, hosted browser suite **22 passed** (including four new responsive/dialog checks), native macOS Electron **3 passed**, production IDE build passed, and all four installer bundles rebuilt/checksums verified. Screenshots inspected at compact/standard/wide sizes. Button source audit found click handlers or intentional form submissions; behavior is covered by the workflow suites.

**Restart:** Normal local browser server and Electron relaunched with saved project/configuration/scene/plan/history signatures preserved. The Mac lock prevented a final live computer-use view of the relaunched desktop; its process was verified and native tests/screenshots passed. No GPU VM was started. See [UI overhaul report](UI_OVERHAUL_20261029.md).

### 29 October 2026 — Workspace access code in the UI

**Request:** Make the workspace access code accessible from the UI.

**Implemented:** Configuration → Workspace access includes explicit Show, Copy and Hide controls. The value clears on leaving the panel, browser-tab hiding or a one-minute timer; clipboard denial selects the code for manual copying. The desktop's native Workspace → Show workspace access code menu also works before sign-in and offers Copy code. The login page points to these desktop controls for first-time access without disclosing the credential. Installed desktops use the installation's access file.

The browser reveal endpoint is IDE-session authenticated, no-store, and separate from the Business API/private runtime. Local Electron uses a narrow trusted-main-frame IPC fallback to read the configured local code, with untrusted/remote origins rejected. The private runtime's static frontend returns 405 for the gateway-only POST route; the native fallback handles both 404 and 405. Source/fixture tests verify authentication, cross-origin denial, Business isolation, native IPC boundaries, menu copy, copy/hide/timeout behavior and clipboard fallback. The initial browser timer test installed its fake clock too late; the test timing was corrected before the final passing run.

**Validation:** 12 gateway/installer backend tests, seven hosted access/layout checks, three native Electron checks, three targeted URDF browser checks and the production build passed. Native URDF tests now explicitly click/focus editable fields before input and wait for the visible configured state; fast native fills had intermittently failed to commit. The web server and desktop were restarted with the feature; installer bundles rebuilt. No actual access code is recorded in this timeline or published screenshots (screenshots use isolated fixture credentials).

### 29 October 2026 — GCP-configured recording; fresh native footage blocked by capacity

**Request:** Record a video with NVIDIA GCP configured, then explain whether Isaac Sim itself can be recorded in action.

**Delivered:** A narrated/captioned 02:16 GCP configuration supplement with actual current UI footage, saved connection and credit safeguards, real startup attempts, visible error handling, native robot-asset guidance and stopped-state verification. Both existing L4 VMs rejected startup with Google Cloud resource-pool exhaustion (zones `asia-south1-b` and `asia-south1-c`). No replacement VM was created. Fresh native motion/viewport footage was therefore not captured; video narration and metadata explicitly state this.

The local recording workspace temporarily selected the standby VM; the normal IDE connection and user projects remained unchanged. Both VMs were verified TERMINATED afterward; disposable recording services were stopped, and the normal local IDE server remains available. Exported H.264/AAC MP4 fully decoded and sampled frames were inspected. See [GCP recording supplement](../artifacts/walkthroughs/README.md).

**Explained:** Native scene-camera RGB capture plus MP4 encoding is suitable for a headless worker; WebRTC is the alternative for recording Isaac's full interface. These capture integrations are not newly implemented or GPU-validated by this recording, and still require an available GPU host.

## Consolidated bug-fix register

| ID | Reported/observed issue | Corrected behavior | Scope/evidence |
| --- | --- | --- | --- |
| B01 | Scene object addition invisible | Immediate draft viewport update; explicit persistence | Scene assets and browser tests |
| B02 | Confusing single/workflow authoring and implicit robot selection | One editable plan/task hierarchy; explicit assignments | P03, runtime/browser suites |
| B03 | Controls too small | Enlarged arrows, yaw ring, increments and touch targets | P09; UI reports |
| B04 | Robot movement missing or delayed in environment | Feedback updates both models continuously | 25 October control tests |
| B05 | Rapid targets/out-of-order responses | Coalescing, cancellation and revision guards | Hosted controls regressions |
| B06 | Simulator changes required manual scene rebuilding | Managed two-way transfer and draft inclusion | Scene handoff contracts/native acceptance |
| B07 | Destination ownership race during handoff | Atomic lease/resource checks and rollback | 25 October follow-up |
| B08 | NVIDIA/robot wordmark alignment | Consistent centering, spacing and baseline | 27/29 October UI checks |
| B09 | Warnings detached from clicked controls or covered dialogs | Persistent in-flow feedback, alert/status roles and scoped placement | 27 October QA |
| B10 | GPU startup remained in stale progress state | Poll final status; show capacity failure; explicit retry | Hosted/Business tests |
| B11 | Rejected login code lacked explanation | Visible themed alert beneath submit | Hosted login tests |
| B12 | Duplicate server start damaged active authority record | Preserve/verify instance identity before cleanup/stop | 27 October QA |
| B13 | Model-loading/relocation/test teardown races | Explicit synchronization and isolated fixture stores | 24/27 October reports |
| B14 | Global robot setup confused with project-instance creation | Independent global wizard and saved model/adapter pairing | 28 October release |
| B15 | Pairings not reliable across browser/device sessions | Server-side binding with reviewed hash and compatibility validation | Global library tests |
| B16 | Shared limits could invalidate initial states | Validate factory/project initial joints, use writable data copies | 28 October release |
| B17 | Global wizard closure could leave simulated controls active | Stop/disconnect before closure | Global library tests |
| B18 | Installer environment/checksum handling | Preserve venv paths; accept official binary-manifest format | Installer-specific tests |
| B19 | Business floor plan disagreed with finished 3D state | Same observed object feedback in both views | 29 October UI review |
| B20 | Hello accessible name and narrow layout timing | Explicit label, focus/reduced-motion checks, stable tests | Welcome checks |
| B21 | Phi-4 fenced JSON/Python responses rejected unnecessarily | Extract one allowed leading fence, then validate | Ollama regressions |
| B22 | Overlarge/misleading task schemas | Compact command-specific required schema | Ollama task drafting |
| B23 | Formatting errors prevented valid drafts | One bounded model-authored schema/JSON repair | No semantic target substitution |
| B24 | Relative lift intent could be lost despite schema-valid tasks | Observed-state grounding plus independent final outcome check | Browser/Business negative tests |
| B25 | SDK draft could imply invented live integration/feedback | Injected-transport contract; explicit unsupported vendor methods; test-only eligibility | Adapter/Ollama reports |
| B26 | Prompt fields exposed in regular setup/inspectors | Internal instructions; private provider metadata; prompt-free new source manifests | LLM privacy tests |
| B27 | Custom LLM calls needed a standard code path | Monaco paste/import/sample; isolated cancellable function workers | 29 October adapter tests |
| B28 | Project IDs hard to locate | Selectable field and copy/fallback beneath project selector | Wordmark/ID browser check |
| B29 | URDF conversion unavailable | Reviewed deterministic import plus optional metadata assistance | Current delivery |
| B30 | Non-cardinal/negative axis mismatch | Vector-axis FK/IK and matching preview | URDF math/control tests |
| B31 | Generic Cartesian Move assumed a gripper | Gripper-optional solver call | Executed imported-gantry plan |
| B32 | Global virtual-template tests had feedback only | Simulated manual joint/tool controls and preview | URDF browser acceptance |
| B33 | Anchored root frames tripped floor validation | Exclude coincident root frames; retain non-root floor checks | Full runtime/URDF plan checks |
| B34 | Backdrop dismissal bypassed Configuration's busy/session guard | Invoke the dialog's permitted close action; pending submissions guard closure | UI overhaul dialog regression |
| B35 | Inconsistent type/spacing, cramped compact toolbars and weak interaction states | Shared workspace skin, responsive toolbar wrapping, consistent hover/focus/selected states | UI overhaul screenshots and 1100/1512/1920-pixel checks |
| B36 | Setup dialogs lacked consistent keyboard containment/focus return | Trap Tab within the active dialog, honor guarded Escape and restore opener focus | Hosted keyboard/busy tests and native acceptance |
| B37 | Workspace access code required Terminal/file access | Guarded reveal/copy/hide in Configuration and pre-login native desktop menu; runtime-only fallback supports static-server 405 | Gateway, UI and native IPC/menu tests |
| B38 | Rapid URDF joint edits could lose a numeric entry | Capture the input string before queuing the React state updater | Discovered during native workspace-access regression checks |

GCP resource-pool exhaustion, GPU quota/billing restrictions and driver installation were operational prerequisites/workarounds, not simulator code defects. They are recorded separately in P08 and the dated cloud entries.

## Current limitations and uncompleted external acceptance

- Real manufacturer hardware/ROS deployments and arbitrary custom SDK transports need actual device acceptance. A simulated contract pass is not that acceptance.
- Physical automatic plan execution remains unavailable; live manual control has separate review/connection/fresh-feedback/arming/ownership requirements.
- Native Isaac GPU acceptance was recorded for educational assets on 27/28 October. It was not repeated for every later local UI/LLM/URDF change, and does not certify newly imported manufacturer geometry.
- Native Isaac editor/WebRTC video streaming and GPU NuRec reconstruction/training are separate services, not established by the simplified browser viewport or room-photo UI.
- Signed desktop installers, native Windows target-host validation, permanent HTTPS/DNS and arbitrary RTX compatibility remain deployment work.
- Local templates deliberately cover a narrow grammar. Phi-4's compound lift remains unreliable; validation correctly rejects the final failing case. The relative-goal checker is not a universal natural-language verifier.
- URDF mimic/coupled, floating and planar joints need additional integration. Xacro must be expanded externally. The current import wizard selects one primary tool frame and does not certify robot mesh collisions/dynamics.
- Separate local/cloud installations keep separate data/libraries; scene handoff within one backend is not automatic cross-machine project synchronization.
- Build/test advisories retained: lazy Monaco bundle size, upstream Three.js Clock deprecation, Starlette/httpx test-client deprecation, and an expected duplicate-ZIP fixture warning. These are not promoted as robot-operation warnings to business users.

## Evidence index

- [Architecture](ARCHITECTURE.md), [implementation roadmap](ROADMAP.md), [task pipeline](TASK_PIPELINE.md).
- [Server checks, 24/25 October](SERVER_VALIDATION.md).
- [QA, 27 October](QA_20261027.md); [later cloud native validation](CLOUD_VALIDATION_20261027.md).
- [Cloud deployment status](GCP_DEPLOYMENT_STATUS.md); [credit-conscious GCP setup](GCP_ISAAC.md).
- [Global library/installer release, 28 October](RELEASE_20261028.md).
- [UI review, 29 October](UI_REVIEW_20261029.md); [real Ollama results](OLLAMA_FUNCTIONAL_TEST_20261029.md).
- [Desktop/browser UI overhaul and restart](UI_OVERHAUL_20261029.md).
- [RoboDE branding and recordings](ROBODE_UI_AND_RECORDINGS_20261029.md); [video chapters](../artifacts/walkthroughs/README.md).
- [Global robot library](ROBOT_LIBRARY.md), [LLM adapter contract](LLM_ADAPTERS.md), [URDF import](URDF_IMPORT.md), [current URDF validation](URDF_VALIDATION_20261029.md).

Private `artifacts/` logs referenced by historical reports remain local evidence; this timeline deliberately does not publish their credentials, raw provider prompts or live access details.


## 29 October 2026 — 0.4.0 recording-enabled edition

**Request:** Make another version that can record the simulated NVIDIA Isaac scene in action.

**Implemented:** Native USD camera / RGB render-product capture in the separate Isaac worker; bounded separate FFmpeg encoding into H.264 MP4; authenticated project-owned recording start/status/stop/history/download APIs; project-local backend caching; recovery after connection loss and worker/runtime restart; Environment camera settings, recording status, in-flow errors and downloads in the shared desktop/web React UI; tutorial guidance; versioned installer edition with the previous archives retained.

**Behavior and fixes:** Capture renders the scene without calling the physics-step API. Scene replacement/reset/disconnect/backend-switch guards preserve an active recording while robot Stop and normal plan/manual command ownership remain independent. Camera primitives live in USD's session layer so native object saves cannot persist the recording camera into the project's USD scene. Downloads check response status and type before saving, preserving inline errors instead of downloading an error response as a video. Gateway responses retain MP4 filenames and hashes. Worker lease expiry finalizes capture; bounded recording activity preserves existing GPU idle-stop and maximum-runtime safeguards. Closing the runtime cancels robot execution before waiting for video export.

**Delivery:** Coherent 0.4.0 package/health version; new archives under `dist/releases/0.4.0-recording/`, baseline copies under `dist/releases/0.3.0/`. Business features and the shared backend remain compatible; the limited Business UI does not gain engineering recording endpoints. See [usage and worker upgrade instructions](SCENE_RECORDING.md) and [release validation](RELEASE_0.4.0_RECORDING.md).

**Validation scope:** Real MP4 encoding/decoding uses synthetic test pixels; worker, API, gateway and UI contracts are tested locally. Native RTX capture remains pending available GCP GPU capacity and deployment of this worker edition. No native motion footage is claimed from the synthetic fixtures. The bounded native acceptance script records an already connected native scene without booting a VM or commanding robots.


**Final 0.4.0 validation snapshot:** 282 Python tests passed; the final camera/API subset passed 20/20. Shared React coverage finished with 31 initial passes and 3/3 focused recording/drag passes after the editor layout correction. Hosted coverage finished with 22 initial passes and 4/4 focused access/layout passes after scoping three ambiguous status selectors. Native Electron production checks passed 4/4. Both production builds and four clean installer archives were verified. Desktop/browser services were relaunched without changes to the 15 fingerprinted saved configuration files. GCP VMs stayed stopped; the native capture acceptance command correctly refused the disconnected scene.


## 29 October 2026 — Native NVIDIA scene recording demonstrated on GCP

**Request:** Run the recording edition and record a demo with NVIDIA simulation running.

**Performed:** Started the existing `robot-ide-isaac-cloud` L4 VM in `asia-south1-b`; deployed the recording worker and bundled FFmpeg with a rollback backup; transferred a separate two-robot demonstration project into Isaac Sim 6.2.0. Two native consecutive-recording regressions passed, followed by an explicitly assigned 18-task plan executing on native articulation feedback. The run passed and stopped feedback was confirmed. The primary camera recording is 42.6 seconds, 1280×720 / 10 fps, with 426 frames, no repeated frames and checksum-verified download. A narrated 1080p walkthrough combines genuine UI footage with native camera footage from that same run.

**Bug fixes discovered by GPU testing:** Isaac 6.2 RGB annotator detach invalidated live articulation views. Camera products are now paused and reused within a bounded scene-owned pool, then destroyed after robots stop before scene unload/shutdown. Added real-USD/fake-renderer regression coverage for paused/reused product lifetime, plus actual L4 capture/control/Stop validation. GPU startup now retries a forwarder that exits while SSH is still becoming ready, using the existing startup deadline.

**Credit safeguards:** Disconnected the native demo, stopped the VM explicitly and verified provider `TERMINATED`; retained the idle watchdog, 7200-second STOP cap and disabled automatic restart. Original project and connection configuration remains separate from the demonstration workspace. See [demo files and evidence](NVIDIA_SCENE_RECORDING_DEMO_20261029.md).


## 29 October 2026 — Installers for every application edition

**Request:** Build an installer for each application version.

**Delivered:** Versioned Windows/Linux x64 Desktop and Server bootstrap ZIPs; Apple Silicon and Intel macOS Desktop ZIPs and disk images; a cross-platform Business companion ZIP with optional desktop shortcuts, phone/browser installation instructions and offline room capture. The Server edition continues to serve both authenticated applications from one backend. macOS uses built-in simulation locally and a separately configured GCP/remote RTX worker for Isaac. Previous release folders remain intact.

**Implementation:** Matching OS/CPU checks, remote setup without local NVIDIA installation, Python 3.12/3.13 support for Mac remote mode, checksum-verified Electron download/cache reuse with safe framework-symlink extraction, generated Mac app launcher with startup logs/error dialog, separate installed Electron profiles, isolated-port startup for acceptance checks, and longer systemd shutdown grace for recording finalization. Business App adds branded installation metadata/icons and keyboard-accessible installation instructions. Public installation metadata contains no workspace data. Business login remains inside its installed navigation scope; the original login URL stays compatible.

**Validation:** Both production builds pass; 289 runtime tests passed before the final scoped-login addition, followed by 18 focused installer/gateway/server tests. Business browser suite passes 11/11; Electron suite passes 4/4. A separate installed Apple Silicon Mac workspace launches the packaged Electron runtime, private API and both production sites, compiles and executes the packaged Wave example in the built-in simulator, confirms stopped feedback and shuts down its owned services. Integrity/privacy checks cover all six main ZIPs, the Business ZIP and both Mac disk images. Installed data and access-code fingerprints survive update. Final evidence is stored with the release in `validation.json`.

**Limitations:** Unsigned bootstrap distributions need Python and internet during setup; no native Windows MSI/EXE or Linux AppImage is claimed. Windows/Linux and Intel Mac installation acceptance still require their target operating systems. Phone installation uses browser/Home Screen installation; it is not an App Store/Play Store package. No GCP VM or physical robot is started by these installer checks.


## 29 October 2026 — GitHub publication preparation

**Request:** Push the completed project and installers to `Theboss12k/RoboDE`.

**Prepared:** Initial source snapshot of all three applications, runtime, examples, installer builders and tests. Saved project folders and every machine runtime file are excluded from Git. Fresh source checkouts seed the canonical examples once, preserving existing saved projects; tests read canonical examples directly. Installer packages are kept as release assets rather than source history. Runtime verification passes 291 tests after the clean-checkout/data separation change. GitHub publication status is reported separately by the actual push/release result.

# RoboDE robotics v2 — local implementation and verification

Status: local development, 30 October 2026. No GitHub push, cloud deployment or GCP VM start is part of this change.

## Architecture and interfaces

The shared React IDE used by Desktop and Server now exposes a resumable global setup: target, reusable driver, URDF, mapping, actuator tests, motion, MOVE test, publish. Legacy definitions remain accessible under an explicit compatibility section. Project robot instances select a published model/driver mapping. The model and vendor driver retain separate identities and content hashes.

Plans use separate `/decompose` and `/bind-commands` operations. The planner returns tasks, clarification questions or an unsupported result; the binder returns typed catalog calls. The dispatcher does not evaluate generated plan Python. Users can add typed tasks/calls without an LLM and repair dependencies before deleting prerequisites. Task changes invalidate revisions. Compiled calls remain readable as a JSON manifest.

Global LLM role settings choose setup, planning and command-binding providers independently. Task selections override the binder. The existing two-argument text function is preserved; image-enabled functions also expose `invoke_multimodal(input, system_prompt, images)`. VLM mode requires a vision-capable provider, a matching scene fingerprint and an image less than 30 seconds old. JSON Schema output is opt-in for compatible chat-completions providers.

## Drivers and mappings

Drivers are bounded Python Transport classes. The worker owns imports and connections. Simulated tests execute that generated class with an injected SDK; no hardware SDK is imported. Tests exercise range endpoints, unchanged peers, whole-vector preservation, whole-batch preflight and Stop. Driver edits clear review, simulated test and hardware qualification status. Failed LLM generations remain editable outside the driver registry.

Mappings preserve URDF joint IDs and add aliases, scale/direction, offset, passive/coupled roles, selected tools/TCPs and mobility settings. Wheel velocity functions use explicit conversions. URDF primitives and retained STL/OBJ/self-contained glTF visuals render in the mapping preview; missing/unsupported mesh formats use a visible marker. Collision geometry can be overlaid. Imported mimic joints require explicit coupled-joint review.

Publishing requires an exact reviewed driver, driver tests, tests covering every independent actuator and a MOVE test for the same mapping hash. Simulation readiness never implies hardware readiness.

## Local Linux worker

From the repository root:

```sh
node scripts/python.mjs -m scripts.robotics_worker build
node scripts/python.mjs -m scripts.robotics_worker start
node scripts/python.mjs -m scripts.robotics_worker status
node scripts/python.mjs -m scripts.robotics_worker stop
```

Docker runs the ROS Jazzy worker on Linux (including Docker Desktop/OrbStack on this development Mac). Linux/WSL2 hosts use the same image. The endpoint binds to host loopback, requires an owner-only local token and defaults to a read-only container. The launcher does not call GCP. Vendor SDKs must be installed deliberately in a derivative worker image before hardware use; USB access requires explicit device passthrough. Keep the physical worker near the device.

MoveIt uses the retained URDF, reviewed tool offsets, explicit start state and numerical KDL IK. OMPL plans joint motion. Nav2 computes a differential-drive path from an occupancy map of reviewed scene primitives; bounded turn/translate stages generate wheel motion. BOTH planning supports a reviewed transit pose, base motion, a stopped-base stage and arm motion, with configurable priority.

Every native motion job owns a separate process and planning scene; its process group is reaped after success, failure or cancellation. MoveIt checks self/environment collision. Conservative interval bounds certify separation between samples and across concurrent robot geometry; uncertain overlaps subdivide, and unresolved bounds return **Incomplete**. Missing collision geometry and unsupported asset collision coverage also return Incomplete. The desktop/API cannot convert this to hardware permission.

References: [MoveIt Python motion planning](https://moveit.picknik.ai/main/doc/examples/motion_planning_python_api/motion_planning_python_api_tutorial.html), [MoveIt Planning Scene](https://moveit.picknik.ai/main/doc/examples/planning_scene/planning_scene_tutorial.html), [Nav2](https://docs.nav2.org/), [Ollama structured output](https://docs.ollama.com/capabilities/structured-outputs).

## Physical execution boundary

The IDE shows a red connection acknowledgement. Connected SDKs must supply timestamped measured positions/velocities, an actual device identity, confirmed stopped feedback and a documented communication-loss watchdog. Simulated feedback cannot satisfy this contract. Ownership is shared with existing manual-control resources.

Physical plan requests refer to an immutable checked revision. Operators first qualify independent actuators with small, explicitly armed qualification revisions, then arm a complete plan for 30 seconds and one use. Starting state, binding hash, cloud runtime plus stopping allowance and feedback freshness are checked again. Coordinated devices share a worker start time. Browser/API heartbeat loss and the independent driver/device watchdog stop the run. Stop requested and stopped confirmed are separate states.

Business App uses the same semantic planning and compilation engine when an LLM is configured. It displays clarification and checking results, can request a physical run and can request Stop; physical arming remains an IDE operation. The deterministic template path remains available without an LLM.

## Validation evidence and limits

Native tests on this Mac's local ARM64 Linux container demonstrated:

- MoveIt/OMPL joint movement on the imported gantry.
- Numerical tool IK to `[0.1, 0.05, 0.35]` metres and rejection of `[50, 50, 50]`.
- Passed native/swept checking on explicit separated collision primitives.
- Rejected a thin obstacle intersecting the trajectory, including an inter-sample finding.
- Nav2 differential-drive path to `[0.3, 0.2]` metres and heading `0.1` radians.

Local Phi-4/Ollama produced a semantic task and a bound `set_base_yaw(value=0.2, unit="rad")` call. An unsafe shoulder sample was rejected by the existing table-clearance check. The final driver-generation attempt used a flat constrained output schema, produced a documented actuator driver and passed the generated-code subprocess tests. Earlier failed attempts remain recorded separately. Ollama 0.12.3 crashed on the original recursive schema; the flat driver schema avoids that failure. Evidence: `artifacts/robotics-v2-local/driver-generation.json`, `phi4-results.json` and the native planning/validation records. The earlier results file is not the final successful driver-generation result.

No real robot or native Isaac GPU validation was performed for this change. Native Isaac now reads measured articulation roots and uses retained URDF packages through the Isaac 6 importer API, but those GPU paths still require native validation. Closing a gripper alone never establishes attachment: the native observation tracker requires an object to follow a short verification lift. It does not attach or teleport the object. Built-in grasps remain explicitly idealized simulation.

Carried objects use conservative rotational bounds and reviewed permitted touch links. Imported environment/payload meshes without reviewed native collision representations, unconstrained passive joints and coupling that differs from retained URDF mimic constraints produce Incomplete. Unobserved real-world obstacles remain outside the configured scene. Native rover navigation does not qualify a real rover's odometry/controller. Physical grasp, release and placement success require measured attachment feedback and, for placement, a measured object pose. Missing observations fail the task rather than establishing success.

Supported driver templates cover scalar SDK setters and SDK dictionary joint-vector writes. SDKs with other signatures need a reviewed wrapper exposing the bounded transport contract. Drivers and SDK installation are deliberate local configuration; arbitrary generated Python is not executed in the API.

Legacy plan records are backed up before repeatable schema migration. Task IDs, robot assignments and dependencies are preserved. Immutable revision files and historical runs are not rewritten.


## Examples and local acceptance

The URDF import fixtures are in `SERVER_CLIENT/server/examples/robots/`:

- `bench_gantry.urdf`: stationary XYZ gantry; use the gantry virtual driver.
- `differential_rover.urdf`: differential base; use the differential-drive virtual driver. Review finite wheel control windows, 0.05 m wheel radius, 0.30 m track, footprint and navigation bounds.
- `mobile_manipulator.urdf`: differential base with an articulated arm; use the mobile-manipulator virtual driver. Configure BOTH, the named tool link and a reviewed transit configuration.

These are fictional simulation fixtures, not manufacturer ratings or hardware-qualified robots. Import and mapping contracts cover all three classes. Native BOTH checks exercise arm-first and base-first planning and the explicit stopped-base phase.

Repeatable local checks:

```sh
npm test
npm run typecheck
npm run server:build
npm run business:build
npm run server:test
npm run electron:test
npm run business:test
npm run test:e2e
ROBOT_DE_NATIVE_TESTS=1 node scripts/python.mjs -m pytest tests/native -q
```

Run Server and Electron browser suites sequentially because both use port 8082. The test harnesses use temporary workspaces and injected fixtures. They do not connect physical devices or start GCP VMs. Browser workflows cover the new complete virtual setup/publish flow, resumable physical-target drafts, role selectors, manual tasks, simulator synchronization, controls, tutorial, access control and inline warnings.

The runtime suite currently passes **321 tests**; its four opt-in native tests are skipped in the ordinary suite and pass separately in the local Linux container. Business browser tests pass **11/11**. The broader IDE workflow run passed 30/32 initially; the two failures exposed a task-selection/view race and an ambiguous test selector. Both pass after the correction. Server browser coverage is **28 tests**: 27 passed in the full run; the remaining failure was a test locator that matched both the workspace and wizard status messages. After scoping it to the wizard, all three robotics setup tests pass together. Electron browser checks pass **4/4**. TypeScript checking and both production builds pass. The final result is recorded in `artifacts/robotics-v2-local/local-verification.json`. Expected non-blocking warnings: upstream Starlette test-client deprecation, a deliberately duplicated ZIP member in a rejection test, a dependency's THREE.Clock deprecation and the Monaco production chunk-size advisory.

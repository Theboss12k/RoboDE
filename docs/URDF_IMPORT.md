# URDF import in RoboDE

Open **Configuration → Robot library → Add robot to library → Import URDF**. The shared React UI provides this flow in both Electron and the browser/server IDE. The Business App uses robots that the IDE has already configured; it does not expose engineering imports.

1. Upload an expanded `.urdf`, or a `.zip` containing the URDF and its meshes. For packages containing multiple URDFs, enter the selected file's path inside the ZIP.
2. Review the extracted robot, links, ordered joint tree, origins, axes, units and limits. Read-only fields came from the URDF. Acceleration, absent velocity/position limits and starting positions need configuration. Suggested zero starting positions must be reviewed and must fit the completed limits.
3. Choose the end-effector link. Optional gripper configuration requires an existing actuator and explicit closed/open positions. Payload stays explicitly unrated unless entered from verified documentation.
4. Optionally expand **LLM assistance**, select a global LLM adapter, and provide vendor documentation. **Suggest robot metadata** returns proposals; **Use suggested metadata** explicitly accepts names/descriptions and, when not already selected, the proposed tool link. Capability suggestions and SDK command mappings remain advisory text. Manufacturer and command claims require quoted documentation evidence. Mechanical values cannot be replaced by an LLM response.
5. **Validate robot definition**, read the limitations, check **I reviewed the URDF robot configuration**, then **Save global robot & continue**. Validation happens outside the active registry. Registration is atomic; no project instance or physical connection is created.
6. Select a clearly labelled **Virtual** or **Physical** adapter in the existing next step, then continue to the isolated simulator test. Global tests allow bounded joint/component commands and tool IK through simulated transport; they cannot arm hardware.

Use [bench_gantry.urdf](../SERVER_CLIENT/server/examples/robots/bench_gantry.urdf) as a fictional working example. Set acceleration to **0.8 m/s²** for `slide_x`, `slide_y` and `slide_z`, review initial values of zero, and choose `tool_tip`. In the simulator test, expand **Standardized task controls**, choose **Move end effector · IK**, and enter **(0.1, -0.1, 0.35) m**. `slide_y` has a negative axis, so the resulting positive joint position moves the tool towards negative world Y. These limits describe the fictional example, not manufacturer hardware.

## Supported structure

- One connected, acyclic URDF tree with fixed, revolute and prismatic joints; branched link trees are retained. Select one named primary tool frame in this wizard.
- General finite nonzero joint axes, including negative and oblique axes, normalized without changing their direction. FK, bounded serial-chain DLS IK and the browser's kinematic renderer use the same vector. Original joint origins and RPY transforms are retained.
- Continuous joints require an explicit finite RoboDE control window; the source keeps the original continuous declaration. This is a control window, not a fabricated mechanical stop.
- Missing acceleration limits are never guessed. A positive acceleration attribute, if explicitly present as a URDF extension, is shown as extracted from that extension.
- A world-root identity transform and an SI scale marker are conversion bookkeeping. They do not invent link lengths. The browser draws a kinematic link preview; it does not load the original robot meshes as certified collision geometry.
- Mimic/coupled, planar and floating joints remain explicit blockers. Disconnected/cyclic trees, duplicate names, invalid numbers, zero axes, inconsistent limits and malformed XML are rejected. No xacro processor or plugin is executed.

Generic joint/component motion and tool IK do not certify grasping, dynamics, collision-free motion or hardware operation. Imported models start with move-home support and simulated joint feedback. Pick/place and physical execution are not enabled by importing a URDF or accepting an LLM suggestion. The existing compiler still validates sampled motion; a structural IK result may fail reachability, joint/rate or sampled scene checks.

## Sources, meshes and Isaac Sim

Upload limits: 32 MB compressed/raw, 100 MB expanded, at most 512 ZIP entries, 25 MB per packaged file and 2 MB for the selected URDF. Archive traversal, absolute/drive paths, symlinks and duplicate filenames are rejected. XML DTD/entities/includes are rejected. There is no external URI fetching.

Package and contained relative mesh references are resolved against supplied files. Missing or ambiguous mesh references are listed and retained as warnings. This permits kinematic preview without pretending native geometry is ready. Supply the missing package before native import.

After saving, **Download URDF source** appears on the global robot card. It returns the original uploaded URDF or ZIP unchanged. The backend also retains extracted source files, URDF SHA-256, mesh hashes, review provenance, warnings and the selected LLM adapter/model version under `runtime/imported_models/<model>/source/`.

Native Isaac setup remains explicit: import the retained URDF/mesh package using Isaac's importer, validate its USD articulation, units/limits and joint mapping, then add it to the approved asset catalog. This feature does not perform native URDF-to-USD conversion or start a GPU VM. Browser uploads and source paths refer to the backend machine. Separate Mac and cloud installations retain separate libraries.

Drafts live under `runtime/urdf_imports/`, outside the active robot registry. Closing/leaving the import flow requests draft cleanup. A failed registration leaves no partial model. Losing a network connection may leave a draft that can be explicitly deleted through the API. The original source copied to a successfully registered model survives draft deletion and backend restart.

## API

- `POST /api/registry/urdf/drafts?filename=robot.urdf&urdf_path=...` — raw binary URDF/ZIP upload; path only needed for multi-URDF ZIPs.
- `GET/DELETE /api/registry/urdf/drafts/{id}` — inspect/delete the private import draft.
- `POST .../{id}/suggest` — `{adapter_id, documentation}`; internal instructions are supplied through the configured LLM adapter.
- `POST .../{id}/validate` — validate a review configuration and preview the converted bundle without registration.
- `POST .../{id}/commit` — require `reviewed: true`, rebuild from the retained source and reviewed values, validate again, and register atomically.
- `GET /api/registry/{model}/source` — download the original source.
- Existing `GET /api/registry/{model}/bundle` — export the converted `.robot.json`.

Review configurations include `id`, `name`, optional `manufacturer`/`description`, `tool_link`, every moving joint's `min`/`max`/`velocity`/`acceleration`/`initial`, optional payload and gripper endpoints, and the review acknowledgment. Provided values cannot override extracted mechanical fields during conversion. Shared definition edits after import use the existing configuration workflow and invalidate affected compiled revisions.

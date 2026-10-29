# Scene preview and 3D imports

In **Environment**, adding or editing objects immediately updates the local viewport. **Focus** centers the camera on an object. The unsaved-preview badge distinguishes local edits from the simulator's saved scene. **Save scene** persists and applies the draft, invalidating previous compiled plans. Reset initializes the saved scene.

With **Built-in simulator** or an updated managed **Isaac Sim** worker selected, choose **Import 3D object**. Supported formats:

| Format | Support |
|---|---|
| GLB | glTF 2 binary geometry, materials and embedded textures |
| glTF | glTF 2 with embedded data-URI buffers and textures |
| OBJ | Geometry, using a default material; no external MTL/textures |
| STL | Binary or ASCII geometry, using a default material |

Files must be self-contained, at most 25 MB and at most one million vertices. External resource URLs and required Draco, meshopt or Basis compressed extensions are rejected. Export an uncompressed, embedded model when needed. Choose Y-up or Z-up for the source, select movable object or obstacle, and set its longest dimension in metres. STL defaults to Z-up; other formats default to Y-up.

Imported geometry is centered on the object's origin and sized to the editable bounding dimensions. The loader reports real loading status and displays an error placeholder when an asset cannot load. Collision/placement checks use the object's declared bounding box, not a detailed triangle collision mesh. The built-in simulator remains an ideal kinematic preview, with no contact physics.

Files are stored immutably under `SERVER_CLIENT/server/projects/<project>/environment/assets/<sha256>/`. World YAML stores mesh references, dimensions, mass and poses. Saves, resets, restarts and project cloning retain referenced geometry. The import first adds a preview; **Save scene** is required to retain its scene placement. Uploads that are not saved into the world do not appear on restart.

Switching to Isaac Sim automatically uploads referenced GLB/glTF/OBJ/STL bytes with checksum verification and converts their static geometry to native Z-up USD. Placement, dimensions, names, role and mass are retained. Native visuals use neutral materials; texture shaders and animations are not translated. Collision bodies use the same declared bounding boxes as planning. The worker installs `trimesh` through `requirements-worker.txt`; conversion does not load external files, URLs or code. New imports can also be saved directly into a connected, updated managed worker.

`POST /api/projects/{project}/assets?filename=model.glb` accepts raw bytes with `Content-Type: application/octet-stream` and returns asset metadata. `GET /api/projects/{project}/assets/{sha256}` serves the immutable file. World saves validate asset references and reject missing or mismatched formats without changing the saved/live scene.

## Robot workspace

Turn on **Robot workspace** in **Environment** or **Plans → Simulation**. Select an individual project robot or **All project robots**, then use **Fit view** to frame its reach. Each robot has a distinct point-cloud color, a sample count and X/Y/Z bounds in world metres. The overlay uses saved model geometry, joint limits and base placement; changing a saved configuration refreshes the samples. It is read-only and does not connect a simulator, move a robot, acquire a control lease or change task assignments.

The cloud samples tool positions from the verified forward-kinematics solver, within actuator limits and with the planner's sampled link-centreline clearance above the table. Obstacles, self-collision, other robots and tool orientation can reduce usable reach. These dots are a geometric aid, not a guarantee that a collision-free path or a requested tool orientation exists. Compile a plan to check motion. Models without verified kinematics show workspace unavailable, rather than an invented envelope.

`GET /api/projects/{project}/robots/{robot}/workspace` returns availability, positions, sample count, world bounds, units and scope. Sampling uses a bounded cache keyed by geometric configuration, so feedback polling does not recompute the cloud. It is also available for disconnected environments without reconnecting them.

## Place and control a robot

In **Environment**, click a robot body, its on-scene name, or its robot chip. Selection opens a second 3D robot model beside the scene and shows translation arrows. Drag the robot body to relocate its base on the ground, or drag an axis arrow to translate along that axis. **Move (G)** and **Rotate (R)** switch between translation arrows and a yaw rotation ring. Empty-space dragging still orbits the camera. Numeric **Base position & rotation** inputs use world metres and yaw radians.

Click a joint or tool on the second model, or choose **Individual joints** / **End effector**. The joint slider, number inputs and incremental buttons update both simulator views continuously, without requiring **Move joint**. Tool position/orientation edits automatically use the configured world frame and IK; unreachable targets report an error and retain the last valid robot pose. Updates pass through the selected adapter. A bounded stream keeps one request in flight and only the newest pending target; Stop, Revert, disconnect and adapter changes discard unsent movement. Feedback cannot overwrite a newer input or reopen a closed preview. Configured serial/branched models show their kinematic skeleton, rather than fabricated manufacturer meshes. The component selector covers actuators that have no visible link geometry.

Adapter Controls also offer continuously updating joint sliders and numeric targets in simulated modes. Connected simulator previews display observed intermediate positions during a movement, rather than waiting for its final response. Live physical controls retain explicit arming and bounded, explicitly sent commands.

Select the configured, reviewed/tested adapter from **Adapter**. The IDE remembers the adapter chosen for each project robot in Robots or Environment. It uses that choice if still reviewed/tested, then a valid saved connection profile, then a matching virtual adapter or the built-in adapter. All draft controls use a separate adapter worker and injected **simulated transport**, including physical SDK/ROS 2 and Isaac adapters. Joint mappings and unit conversion are exercised, but these controls never connect to hardware or the remote GPU scene. Feedback is explicitly labeled simulated. **Stop** distinguishes a request from confirmed simulated stopped feedback. Existing explicitly armed live controls remain in Robots; native Isaac controls remain under the environment connection tools when the draft inspector is closed.

**Use as starting point** closes the draft transport and commits the selected robot's base pose and desired initial joints together, then updates the selected simulator. Applying checks limits, sampled static link/obstacle and inter-robot clearance, stopped state, held objects, ownership and stale source configuration/feedback. Existing runs and immutable revisions are preserved; affected revisions require recompilation. These checks are not a continuous collision or hardware safety certificate. **Revert**, including closing the inspector, discards that robot's preview without changing saved configuration or simulator state. Save object drafts before applying a robot starting point.

For Isaac Sim, Apply requires a managed worker (`--project-scene` or an approved asset catalog). It reloads the native scene within its existing exclusive lease, then restores current object positions and other robots' measured joint positions. Physics velocities reset. If a native reload fails, the saved robot configuration is restored and the connection is closed; the GPU scene may require a managed reconnect/reload. Desktop contract tests do not establish native GPU acceptance.

API additions:

- `POST /api/projects/{project}/controls` accepts a test-only `preview: {positions, base_pose}` seed. A preview cannot use `environment` or `live` mode.
- `PUT /api/controls/{session}/preview-base` updates only an isolated preview's IK frame.
- `GET /api/controls/{session}/tool-poses` returns current tool XYZ values in the configured world frame.
- `PUT /api/projects/{project}/robots/{robot}/starting-state` accepts `base_pose`, `positions`, `expected_instance` and `expected_positions`. The latter two are the saved instance and actual joint feedback captured when editing began; stale drafts are rejected.
- Managed workers expose lease-owned `PUT /v1/sessions/{session}/scene` for reloading the same project/robot set. Fixed scenes, moving robots and other projects are rejected.


## Switch simulators without rebuilding the scene

After configuring the worker connection once, use **Simulation backend** to switch between built-in and NVIDIA Isaac Sim. The IDE saves pending object drafts and transfers all project instances, base placements, the current stopped joint configuration, objects and referenced mesh assets. Captured rooms are uploaded automatically when their source package is available and the worker enables `ROBOT_IDE_ALLOW_ROOM_UPLOADS=1`. Returning to built-in uses measured native joint positions and object poses and persists that simulator state. It does not rewrite saved starting configurations, compiled artifacts or historical runs. Backend changes make previously compiled revisions stale.

Stop robots, close shared simulator controls and release held objects before switching. Grasp constraints and velocities are not transferred. Failure restores the previous backend choice and keeps its scene; a failed native connection may require explicit reconnect. If Isaac is unreachable when returning to built-in, the IDE explicitly reports that it opened the saved starting scene, rather than claiming current GPU poses were transferred. Ordinary Connect/lease renewal reads an existing scene without replaying a completed hand-off.

Start a managed worker with `--project-scene` for automatic educational demo robot construction and object editing. Manufacturer models require their matching BOT definitions and an approved USD/joint mapping in `--asset-catalog` once. Missing or unsupported assets reject the transfer before replacement; they are never silently omitted. Fixed `--manifest` workers remain attach-only and cannot receive an automatic scene switch. First-time Isaac installation, host credentials and GCP billing/quota are still required. Native GPU acceptance is separate from offline USD and HTTP contract tests.

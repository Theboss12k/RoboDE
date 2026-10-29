# Isaac Sim worker and multi-robot cell

Robot IDE now includes the HTTP adapter, authenticated worker, native Isaac Sim bridge, and a self-contained educational USD scene builder. The same assigned workflow can run against local preview or the GPU worker. **The transport/scheduler and USD structure are tested on this Mac; native PhysX execution has not been tested here because no compatible GPU host is connected.**

The native bridge targets **Isaac Sim 6.2.x** using the documented legacy Core API (`World`, batched `Articulation`, `RigidPrim` and `XFormPrim`). Its version check rejects a different simulator release. Those APIs are deprecated in 6.2; update and rerun the adapter/native acceptance suite before changing that version. References: [Core prim API](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/py/source/deprecated/isaacsim.core.prims/docs/index.html), [articulation hierarchy](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/dev_guide/rigid_bodies_articulations/articulations.html).

For GCP, project robot loading and native box object add/remove, use the [managed-worker walkthrough](GCP_ISAAC.md). The fixed-manifest workflow below remains supported.

## How manufacturer robot models are imported

Robot IDE's `.robot.json` import registers BOT metadata: actuators, units, limits, kinematics, capabilities and initial configuration. It does **not** import native robot geometry into Isaac Sim. The command wizard's **Virtual → Isaac Sim** choice configures an adapter; its built-in test window still exercises isolated simulated transport, not native GPU physics.

For a manufacturer asset:

1. On the GPU host, import the manufacturer's **URDF plus referenced meshes** with Isaac Sim's URDF importer, or load a prepared robot **USD**. NVIDIA documents URDF → USD import and articulation setup in its [6.2 importer guide](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/importer_exporter/ext_isaacsim_asset_importer_urdf.html).
2. Configure/inspect the articulation root, fixed/mobile base, joint axes, limits, signs, mass/inertia, collision shapes, drive settings and gripper behavior. Resolve renamed USD joint names explicitly. Save a standalone robot USD for a managed catalog; the worker composes world objects, physics and placements automatically. A complete prepared cell is only needed for legacy fixed-manifest mode.
3. Register the corresponding BOT definition and add matching project instances in Robot IDE. Deploy the same model/version, initial configuration and world definitions to the GPU checkout. Imported models reside in `SERVER_CLIENT/server/robot_system/runtime/imported_models/<model>/`; the worker now resolves that library as well as built-in registry models. Copy matching definitions to the same location on the GPU host.
4. Add the model USD, checksum, articulation root and actuator → USD DOF mapping to the [managed asset catalog](GCP_ISAAC.md#3-import-and-approve-manufacturer-robot-assets-on-the-vm) once. Alternatively, legacy fixed mode uses a complete `worker.yaml` as described below.
5. Validate the native adapter integration before enabling the imported model's Isaac adapter metadata. Imported model metadata alone is not native validation. The connected worker checks the exact deployed model, articulation mapping, limits and placement. Pose tasks require configured analytic or serial-chain IK; direct standardized actuator/component tasks bypass IK. Importing an asset alone does not provide a collision planner.
6. Start the authenticated managed worker, configure its URL/token, and select **Environment → NVIDIA Isaac Sim**. The project scene transfers automatically. Repeated Connect reads state; Reset applies saved initial values. Perform native acceptance below on the GPU.

The included `build_demo_scene` script constructs the educational analytic arm from primitive USD geometry. It is a demo cell builder, not a general URDF/CAD importer. Native model comparison ignores the derived desktop `planning_supported` flag while continuing to compare actual model definitions, mappings, versions and limits.

## GPU setup

Use a supported NVIDIA GPU host with Isaac Sim 6.2 installed. Keep the Mac desktop and GPU worker on matching repository revisions. The commands below run from `Robot_IDE/SERVER_CLIENT/server` on that host; replace `/opt/isaacsim/python.sh` with the actual Isaac Python launcher.

```sh
cd /path/to/Robot_IDE/SERVER_CLIENT/server
/opt/isaacsim/python.sh -m pip install -r requirements-worker.txt
/opt/isaacsim/python.sh -m simulation.isaac_sim.build_demo_scene \
  --project dual_arm_cell --output robot_system/runtime/isaac_cell

# Use your own randomly generated secret, at least 16 characters, on both hosts.
export ISAAC_WORKER_TOKEN='your-worker-secret'
/opt/isaacsim/python.sh -m simulation.isaac_sim.serve \
  --manifest robot_system/runtime/isaac_cell/worker.yaml
```

The builder creates `cell.usda`, per-instance configurations and a checksum-bound `worker.yaml`. The USD includes two articulations, ten driven joints, rigid-body apples, basket walls, a ground/table and gripper contact materials. It uses the fictional educational BOT model; it is not a manufacturer asset and still needs physics tuning and acceptance on the GPU. Use `--project apple_transfer` for one arm.

The builder can also be checked offline with `usd-core`; that validates USD structure and units, not physics behavior. `usd-core` is optional on the Mac and must not replace Isaac's bundled USD/PhysX packages on the GPU.

For a remote host, leave the worker bound to loopback and forward it:

```sh
ssh -N -L 9100:127.0.0.1:9100 user@gpu-host
```

In the **IDE server's `SERVER_CLIENT/server/.env`**, set:

```dotenv
ISAAC_WORKER_URL=http://127.0.0.1:9100
ISAAC_WORKER_TOKEN=your-worker-secret
```

Restart Robot IDE, select **Dual arm cell**, open **Environment**, and choose **NVIDIA Isaac Sim** in **Simulation backend**. Connect reads the current cell; it does not apply saved initial positions. Use **Reset simulator** explicitly to initialize the GPU scene. Open **Plans**, create a named plan, generate tasks from the two default robot goals, compile and select **Simulate**.

One worker owns one physics cell and one project lease. Switch that project back to **Built-in simulator** before connecting another project. A lost connection cannot report a verified stop; the worker's lease watchdog requests a stop when its heartbeat expires.

## External scene manifests

For a custom USD cell, the deployment manifest supplies:

- Absolute `scene` path and its `scene_sha256`.
- `physics_dt`, positive and no larger than 1/60 s; the 30 Hz timeline must be divisible by this timestep.
- `robots`: each entry has `instance_file`, articulation `prim_path`, and a complete mapping from BOT actuator ID to USD DOF name.
- `objects`: the common world-object definitions, including type, size and mass.
- `object_prims`: a matching ID-to-USD-prim path map. Movable objects must be dynamic rigid bodies; regions and obstacles may be transforms over collision geometry.

The worker checks robot IDs, model versions, full BOT definitions, base translations/yaws, object IDs/geometry/mass, joint mappings and declared limits against USD limits. Project and scene coordinates use metres and Z up. The local template planner supports the demo arm. Capability-aware LLM drafts use the standardized task contract and configured IK; arbitrary manufacturer contact behavior still requires native validation.

## Execution semantics

- One authenticated `POST /v1/sessions` leases the existing cell without moving it.
- `GET .../state` returns timestamped simulated joint states, stopped status, and observed object poses.
- `POST .../step` atomically submits the complete cell's joint targets and advances one shared physics interval. Every tick has a strictly increasing sequence number. Invalid/duplicate/partial commands are rejected before advancing.
- Native execution uses controller **targets**, never `set_joint_positions` or predicted object poses. Object movement comes from physics and observations. Joint/object state setters exist only in explicit simulator reset.
- `POST .../stop` holds measured positions and checks measured joint velocities. Requested stop and verified stop remain separate.
- `POST .../reset` explicitly initializes simulator state. `DELETE` releases the cell after requesting stop.
- Every Isaac/Kit call runs on the process's main thread through a queue. The HTTP event loop runs on another thread; all robots still share one physics clock.
- The Mac adapter rejects stale timestamps, mismatched robot sets, incorrect sources, worker faults and unexpected tick acknowledgements. Contract-test workers cannot masquerade as native Isaac Sim.
- Results record worker version, root USD checksum, physics-observation availability, observed outcomes and stopped confirmation. `physics_validated` remains false because the application does not claim a continuous collision or physical safety certificate.

## Acceptance still required on the GPU

1. Build/load the demo USD and confirm articulation DOFs, base frames, drive units and joint signs.
2. Explicitly reset, run move-home and verify actual feedback, command tracking and cancellation for every arm.
3. Run parallel and dependency-ordered pick/place. Tune contact drives/friction if needed; never replace a failed grasp with a synthetic attachment.
4. Confirm dropped objects fail outcome checks and final placements remain valid after the final stop/settling interval.
5. Test worker restart, heartbeat expiry, authentication failure, mismatched assets, timeout and mid-run disconnect.
6. Capture simulator logs, asset versions and physics evidence before claiming native acceptance.

Automatic plan execution remains simulation-only. Neither native physics nor built-in simulation grants physical execution authorization. Separate armed ROS manual controls are documented in [adapter setup](ADAPTERS.md).

## Launch local Isaac from Electron

Open **Environment → Isaac Sim setup → This computer** on Windows/Linux with a supported NVIDIA GPU. macOS shows why native local launch is unavailable and offers **GCP GPU VM** instead. The panel checks the backend host, so a browser connected to a Linux server configures that server's installation.

1. Install Isaac Sim **6.2.x** using NVIDIA's installer, accept its license, and run the compatibility checker. The IDE does not redistribute Isaac, silently accept its license or install drivers.
2. Choose **Isaac Python launcher**. Electron opens a native file picker for `python.sh`, `python.bat` or an Isaac-enabled Python executable. In a browser, enter its absolute server path. With Windows batch launchers, installation/catalog/checkout paths must not contain shell expansion characters.
3. Install the worker requirements once in Isaac's environment. From PROJECT on Linux:

   ```sh
   /opt/isaacsim/python.sh -m pip install -r SERVER_CLIENT/server/requirements-worker.txt
   ```

   Or PowerShell:

   ```powershell
   & 'C:\isaacsim\python.bat' -m pip install -r SERVER_CLIENT/server/requirements-worker.txt
   ```

4. Keep **Automatic project scene** selected for the registered educational demo robots; no scene file is needed. Manufacturer models use an approved **robot USD catalog** with matching deployed BOT definitions. **Fixed cell manifest** is advanced, attach-only mode and cannot receive an automatic scene switch.
5. Use **Generate worker token**, **Save worker connection**, then **Check local setup**. This preflight checks host support and required paths, not GPU physics. A managed local worker uses `http://127.0.0.1:PORT` and receives the saved token through its environment, never command-line arguments.
6. Select **Start local Isaac Sim**. Startup runs separately from the desktop/API process. Watch status and **View simulator log**; first launch can take several minutes. **Open the native Isaac Sim window** is on by default.
7. Select NVIDIA Isaac Sim as the Environment backend. The IDE starts the configured local worker, waits for readiness and transfers the current scene and poses automatically. You can also start/check it separately. Existing task execution, joint/tool controls and Save scene object edits use the same native worker. Returning to built-in transfers observed state back; saved starting configurations remain unchanged.
8. **Stop local Isaac Sim** releases idle native project connections and terminates the process tree the IDE launched. Active execution/manual controls block shutdown. Closing the backend also closes its managed local worker. An externally launched worker is not adopted or terminated: choose **Existing worker** for that case. A process exit is distinct from confirmed stopped robot feedback.

Startup verifies the worker protocol, simulator version and launch identity, and rejects another service occupying the port. A timeout or failed startup reaps the owned child. Logs and configuration stay in private, ignored runtime storage; returned log tails redact the saved worker token. Native GPU rendering, contacts and driver compatibility still require acceptance on the actual Windows/Linux GPU host.

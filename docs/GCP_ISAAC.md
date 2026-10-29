# Use a GCP VM as the native Isaac Sim workspace

The IDE server controls an authenticated worker running inside Isaac Sim on the VM. The IDE's 3D scene shows observed state; the VM remote desktop shows Isaac Sim's native viewport and tools. The IDE can start/stop an existing configured VM on demand. It does not create a project, billing account or GPU VM automatically.

## 0. Start without an existing Google Cloud project

1. Sign in to the [Google Cloud Console](https://console.cloud.google.com/). Use the project selector at the top, choose **New project**, name it **Robot IDE**, and create it. Copy the **Project ID** (not the display name or project number). See [Google's project instructions](https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects).
2. Open **Billing**, create/link a billing account, and enable billing for this project. GPU VMs require a **Paid billing account**: a non-billable Free Trial account cannot add GPUs or request quota increases. Activating paid billing can charge your payment method for eligible usage outside remaining credits. Complete payment/account verification directly with Google; do not paste payment details or credentials into chat. See [Google's Free Trial restrictions](https://docs.cloud.google.com/free/docs/free-cloud-features) and [billing setup](https://docs.cloud.google.com/billing/docs/how-to/modify-project).
3. Open **Compute Engine** and enable its API when prompted. Under **IAM & Admin → Quotas & System Limits**, check/request capacity for one L4 GPU in the intended region and the applicable global GPU quota. Approval and hardware capacity are separate prerequisites. See [GPU quota restrictions](https://docs.cloud.google.com/compute/docs/gpus/about-gpus).
4. Once billing and quota are ready, record your Project ID and preferred region. Continue with the VM configuration below. Choose a nearby supported region for interactive viewport latency; do not create a CPU-only VM as a substitute for Isaac's GPU requirements.

The project/account creation and payment verification steps must be completed by the account owner. No VM, billing account or cloud project has been created by the IDE setup guide.

## 1. Create a new GPU VM

For an initial one/few-robot workspace, start with this configuration. It is a starting point, not a performance guarantee for complex sensors or large scenes.

| Setting | Starting configuration |
| --- | --- |
| Machine | `g2-standard-8` (8 vCPUs, 32 GB RAM) |
| GPU | One NVIDIA L4, 24 GB VRAM (included in G2) |
| OS | Ubuntu 24.04 LTS, x86_64 |
| Boot disk | 200 GB SSD persistent disk; increase for large asset collections |
| Provisioning | Standard/on-demand for an interactive workspace |
| Simulator | Isaac Sim 6.2.x, matching this worker |
| Access | SSH tunnel for Robot IDE; remote desktop for the native Isaac GUI |

G2 specifications come from [Google's machine table](https://docs.cloud.google.com/compute/docs/gpus/). Isaac's [6.2 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html) list 32 GB minimum RAM and a tested Linux driver of 595.58.03; verify the installed driver with the compatibility checker. Larger workloads may need more RAM/VRAM. A100/H100 lack the required RT cores and are not supported for this application.

Before creating the VM, create/select a Google Cloud project, enable billing and the Compute Engine API, and obtain L4/G2 GPU quota in a supported region. A zone advertising the machine type does not guarantee GPU quota or current capacity. Review the Console's cost estimate before creation; GPU compute is billed while running, and retained disks remain billable when stopped.

Use [Google Cloud Shell](https://console.cloud.google.com/cloudshell) if `gcloud` is not installed on your Mac. In Cloud Shell, substitute your actual project ID:

```sh
gcloud services enable compute.googleapis.com --project=YOUR_PROJECT_ID
gcloud compute machine-types list --project=YOUR_PROJECT_ID \
  --filter='name=g2-standard-8' --format='table(name,zone,guestCpus,memoryMb)'
```

Choose a listed zone with sufficient GPU quota. [Google's instance creation guide](https://docs.cloud.google.com/compute/docs/gpus/create-gpu-vm-g-series) describes the Console options. Alternatively, this command **creates a billable VM** when run; replace both placeholders first:

```sh
gcloud compute instances create robot-ide-isaac \
  --project=YOUR_PROJECT_ID --zone=YOUR_GPU_ZONE \
  --machine-type=g2-standard-8 \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=200GB --boot-disk-type=pd-ssd \
  --maintenance-policy=TERMINATE --no-restart-on-failure \
  --max-run-duration=2h --instance-termination-action=STOP \
  --no-service-account --no-scopes \
  --metadata=enable-oslogin=TRUE
```

This assumes the project's default VPC/subnet exists. Otherwise choose your organization's approved network/subnet in the Console. OS Login/IAP access and GPU quota can require administrator assistance. Do not add public HTTP/firewall access to the worker's port 9100. A new Ubuntu VM does not yet include the NVIDIA driver, Isaac Sim or a remote desktop.

When finished working, stop the VM using the Console or:

```sh
gcloud compute instances stop robot-ide-isaac \
  --project=YOUR_PROJECT_ID --zone=YOUR_GPU_ZONE
```

## 2. Install the GPU runtime and Isaac Sim

Follow NVIDIA's [Isaac Sim 6.2 cloud setup](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_cloud.html) and [GCP instructions](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_advanced_cloud_setup_gcp.html). Choose a compatible RTX-capable GPU and sufficient memory/storage for your assets, and run the version's compatibility checker. Google's [GPU machine documentation](https://docs.cloud.google.com/compute/docs/gpus/) lists G2/L4 and G4/RTX PRO 6000 families; quota, availability and supported drivers depend on the region and deployment. Do not substitute an arbitrary compute-only GPU.

Install a supported NVIDIA driver using [Google's GPU driver instructions](https://docs.cloud.google.com/compute/docs/gpus/install-drivers-gpu), then install Isaac Sim **6.2.x** and configure remote desktop using NVIDIA's cloud deployment guide. A shell-only/headless session does not provide the native editor UI; use a desktop session and launch the worker with `--gui` for that workflow. Copy this repository to the VM, keeping model definitions and code versions synchronized with the desktop. Install the worker packages using Isaac's own Python:

```sh
cd /path/to/Robot_IDE/SERVER_CLIENT/server
/opt/isaacsim/python.sh -m pip install -r requirements-worker.txt
export ISAAC_WORKER_TOKEN='REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_16_CHARACTERS'
```

Keep the worker's port bound to loopback. Do not open port 9100 publicly. These commands assume an installed Isaac launcher; a container deployment must mount the checkout and asset paths and use its corresponding Python launcher.

## 3. Import and approve manufacturer robot assets on the VM

**For the registered educational demo robots, skip the catalog and use `--project-scene` below.** Custom manufacturer robots need their BOT definitions copied to the worker and a USD/joint mapping approved once; scene switching then reuses that mapping automatically.

Use Isaac's [URDF importer](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/importer_exporter/import_urdf.html) with the robot's URDF and referenced meshes, or use an existing USD asset. Inspect the articulation root, limits, drive configuration, joint directions, mass/inertia and collision shapes in the native UI. Save a standalone robot USD with a default prim, local resolved dependencies and metre/Z-up coordinates.

Import the matching `.robot.json` BOT definition into the IDE; deploy those same model files to the worker's built-in or `SERVER_CLIENT/server/robot_system/runtime/imported_models/<model-id>/` library. The USD model and BOT metadata serve different purposes. Generic pose planning needs configured kinematics as described in [the task pipeline](TASK_PIPELINE.md).

Create an **operator-owned asset catalog** on the VM. Robot IDs below are model IDs, not project instance IDs:

```yaml
# /data/robot_assets/catalog.yaml
robots:
  your_robot_model:
    usd: /data/robot_assets/your_robot.usd
    sha256: REPLACE_WITH_SHA256_OF_USD_FILE
    # Relative to the USD default prim; empty means that prim is the articulation.
    articulation_path: ""
    joints:
      base_yaw: actual_base_dof
      shoulder: actual_shoulder_dof
      elbow: actual_elbow_dof
      wrist: actual_wrist_dof
      gripper: actual_gripper_dof
```

Use `sha256sum /data/robot_assets/your_robot.usd` on the VM to obtain the root asset checksum. Map **every** configured actuator to its USD DOF. Pin and deploy referenced meshes/layers alongside the asset: a root-layer hash alone does not hash its dependencies. The catalog must contain every model used by the selected project. The worker rejects missing assets, mismatched definitions and incomplete mappings before loading, then validates the actual articulation DOFs and limits.

## 4. Start a managed worker

```sh
/opt/isaacsim/python.sh -m simulation.isaac_sim.serve \
  --project-scene --host 127.0.0.1 --port 9100 --gui
```

Use `--asset-catalog /data/robot_assets/catalog.yaml` instead of `--project-scene` for approved manufacturer robot assets. The project scene is composed automatically in both managed modes; no per-project scene manifest is needed.

`--gui` opens Isaac in the VM's remote desktop. Omit it for a headless worker. Use one worker process per cell. Managed scenes are saved under private worker runtime storage, or `managed_scenes/` next to a supplied catalog; each load gets a new folder. Loading creates a new stage and discards the previous stage's unsaved state. Native joint drives are used during execution, rather than teleporting robot joints. Explicit Reset and simulator hand-off initialize joint/object positions; execution uses observed physics feedback.

The original `--manifest /path/to/worker.yaml` mode remains available for prebuilt cells. Fixed cells do not support scene object CRUD.

## 5. Connect from Robot IDE

On the computer running the IDE backend, start a tunnel (fill in your GCP values):

```sh
gcloud compute ssh VM_NAME --project=PROJECT_ID --zone=ZONE -- -N -L 9100:127.0.0.1:9100
```

In **Environment → Isaac Sim setup → GCP GPU VM**:

1. Set worker URL `http://127.0.0.1:9100` and the same worker token. GCP project/zone/VM fields identify an existing VM and generate the tunnel command. Enable on-demand GPU after installing the shutdown guard below; this adds lifecycle control and SSH port forwarding without provisioning a VM.
2. Use a managed worker (`--project-scene` or `--asset-catalog`). Simulator switching always transfers the current scene. **Rebuild scene on a fresh connection** is advanced and does not control switches. Fixed manifests remain attach-only.
3. If the default Google Cloud SSH key requires an interactive passphrase, configure a dedicated owner-only key under **SSH authentication → GCP SSH key file**. Enter its absolute path on the IDE server. The IDE passes its public key to OS Login with a two-hour expiry; the private key stays on the server and is never sent to the worker. Leave this blank to use the default Google Cloud key. Save the connection and test it. Tokens are stored in owner-only runtime files and never returned in API responses or plan artifacts. Existing `.env` URL/token settings remain fallback defaults.
4. Select **NVIDIA Isaac Sim**. The IDE starts a configured on-demand VM, waits for readiness, and transfers robots, placements, stopped joint positions, objects and imported static mesh files automatically. It keeps the previous simulator if transfer fails. Returning to built-in transfers observed native poses back. Saved starting configurations stay unchanged; Reset applies those separately. See [scene transfer behavior and mesh limitations](SCENE_ASSETS.md#switch-simulators-without-rebuilding-the-scene).
5. Expand **Control robots in Isaac Sim**, select a robot and Connect controls in **Connected environment** mode. Use joint setpoints or standardized task controls. The native articulation receives targets; the panel reports observed joints and Stop confirmation. Close controls before executing a plan or editing objects.

Keep the native timeline under worker control while using IDE execution. Native UI edits can change the scene; reconnect/reload matching metadata before planning if articulation structure or limits change.

## 6. Add/remove objects

With a managed worker connected and all robots stopped, use the Environment object editor. Add an object, region or obstacle, set world position/size/mass, or remove one; then **Save scene**. The worker creates/removes native USD cube geometry and corresponding dynamic/static PhysX objects and returns observed poses. Regions are visual destination volumes, not container walls. Edits are saved in the managed manifest/USD and invalidate compiled plan snapshots. PhysX handles are rebuilt while the scene is stopped. The measured joint positions become the temporary reset defaults, so editing objects preserves the current robot poses rather than applying saved starting configurations.

GLB/glTF/OBJ/STL static meshes transfer automatically from the built-in simulator to a managed native worker through authenticated, checksum-verified uploads (25 MB per upload). Conversion preserves geometry with neutral materials and bounding-box collisions; textures and animation do not transfer. Manufacturer robot USD loading uses the approved catalog. Changing robot count/models/base placement requires loading a new managed scene, rather than editing live articulation topology.

## Validation boundary

The offline suite and native GPU checks are separate. Offline automated tests cover authentication, exclusive leases, schema/units/limits, approved USD composition/checksums, stopped-only object edits, client feedback and desktop controls. They do **not** run native PhysX or verify your GCP GPU. Before relying on a native robot, verify DOF signs, drives, joint tracking, contacts, gripper behavior, object insertion/removal, stop and disconnect handling on the VM. SDK drafts and simulated feedback never constitute physical hardware validation.

Generated educational demo arms disable internal contacts between their overlapping box proxies; contacts with environment objects remain enabled. Use approved manufacturer geometry to validate a real robot's self-collisions. Native feedback normalizes only limit excursions within 10 micrometres or 10 microradians to handle PhysX solver slop. Raw corrected values and their reported boundaries are available in worker health under `feedback_limit_corrections`; larger excursions remain errors. Incoming command limits are unchanged.


## 7. On-demand startup and automatic shutdown

The default proposed policy is **10 minutes without GPU work → STOP**, plus a **2-hour maximum runtime per boot → STOP**, including active work. Adjust these to fit reconstruction jobs and your spending limit. Stopping preserves persistent disks; it does not delete the VM. The maximum duration is a per-session limit, not a daily/monthly monetary cap. Alerts-only budgets provide notifications, not a hard spending cap. Google also offers [spend cap budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps) for selected API services; Compute Engine is not currently listed among the eligible services, so these do not replace VM shutdown safeguards.

The business app, Python API and capture storage stay on a separate host (currently the Mac). Opening pages, polling status, voice recognition and uploading photos never boot the GPU VM. The business app's **Start GPU processing**, an explicit Isaac connection, or reconstruction submission starts it when on-demand is enabled. Native state/control sessions are shared exclusively across projects. Active reconstruction sends work heartbeats even when the browser/Mac disconnects. Health/inventory/state polls do not reset the GPU idle timer.

Google Cloud enforces [`maxRunDuration` with `instanceTerminationAction=STOP`](https://docs.cloud.google.com/compute/docs/instances/limit-vm-runtime). Before each start, the IDE checks this limit and disables automatic restart on failure; it refuses to adopt an unprotected running VM. Startup failures trigger a stop for a VM started by the IDE. A persistent guest watchdog independently powers off the VM after idle time, even if the desktop/API disappears. Its fresh heartbeat and matching idle timeout must be visible in worker health before startup is accepted. A provider stop can interrupt a reconstruction; increase the limit explicitly beforehand if the workload needs longer.

### Install the guest safeguards once

The example units in `SERVER_CLIENT/server/integrations/gcp/systemd/` assume `/opt/Robot_IDE`, a `robotworker` account, Isaac at `/opt/isaacsim`, and a separate installed CUDA/3dgrut environment at `/opt/3dgrut-env`. Adapt paths/account to your VM. Install Python dependencies in the watchdog venv and worker environments first. Enable the watchdog **after** installing/configuring the workers so its idle timer does not interrupt installation.

1. Create `/var/lib/robot-ide/activity` and `/data/nurec-jobs`, owned by the worker account. Both workers must use the same activity directory. Persistent reconstruction output belongs on the retained disk.
2. Create `/etc/robot-ide/workers.env`, owner root, group readable by the worker account, mode `0640`, with `ISAAC_WORKER_TOKEN`, `NUREC_WORKER_TOKEN`, `ROBOT_IDE_ACTIVITY_DIR=/var/lib/robot-ide/activity`, `NUREC_JOBS_ROOT=/data/nurec-jobs`, `THREEDGRUT_ROOT=/opt/3dgrut`, and `ROBOT_IDE_ALLOW_ROOM_UPLOADS=1`.
3. Copy the three `.service.example` templates to `/etc/systemd/system/` with `.service` names. The watchdog runs as root only to call `systemctl poweroff`; workers run unprivileged. Keep the code and systemd files operator-owned. Its `--idle-seconds 600` must match the IDE's configured idle minutes.
4. Run `sudo systemctl daemon-reload`, then `sudo systemctl enable --now robot-ide-idle-guard robot-ide-isaac robot-ide-nurec`. Confirm all services are active and both worker health endpoints report the watchdog active.
5. Stop the VM. In Robot IDE's **Environment → Isaac Sim setup → GCP GPU VM**, save project ID, zone, existing VM name, loopback worker URL/token and **On-demand GPU**. The default SSH mode uses IAP; authorize [IAP TCP forwarding](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding), OS Login, and firewall access to SSH from Google's IAP range. Do not expose the worker ports. Authenticate on the workspace host with `gcloud auth login`; no service-account key should be pasted into the app or chat.
6. Use **Start GPU VM**, then check status until ready. On-demand startup forwards local 9100 and 9200. Do not run duplicate manual tunnels on the same ports. Use **Connect / read state** to load the project; **Stop GPU VM** disconnects idle Isaac sessions and refuses active plan/manual-control/reconstruction use.
7. Verify on the real VM: leave the app open without issuing GPU work; it must stop after the idle timeout. Start a reconstruction, close the app and verify it continues until done or the hard cap. Verify the maximum runtime in Google Cloud Console. These cloud acceptance checks have not been run without your project/access.

The guest timer measures IDE-issued simulation/control work and reconstruction, rather than desktop login presence. Editing directly in the native GUI does not emit work heartbeats: plan your native editing session within the idle window or explicitly refresh work via the IDE. The provider hard cap remains in effect in all modes. This limitation matters when configuring a remote desktop workflow.

### What is needed from your new Google Cloud account

- Project **ID** with Compute Engine API enabled and **Paid billing** activated. A Free Trial account cannot add GPUs; upgrading retains eligible remaining credits but allows paid usage. See [Google's current trial restrictions](https://docs.cloud.google.com/free/docs/free-cloud-features).
- Preferred region, monthly spending target and acceptable maximum GPU session. Confirm quota for one supported RTX-capable GPU (the G2/L4 starting configuration above), including the applicable regional/global quota. Quota approval does not guarantee capacity.
- Local Google Cloud CLI login and permissions to inspect/start/stop/configure this VM plus IAP/OS Login. Once selected/created, the zone and VM name and installed Isaac/3dgrut runtime are needed for the connection.
- A permanent hostname/domain or approved separate web host if phone access must remain available while this Mac is off. Keep that lightweight host and capture storage separate from the GPU lifecycle.

Stopped VM CPU/GPU compute charges end, but retained [disks, snapshots and some IP resources can still be billed](https://docs.cloud.google.com/compute/docs/instances/stop-start-instance). Avoid idle static IPs and reservations for an initial credit-conscious setup. No GPU resources have been created or charged by this implementation; cloud activation needs your project details and authentication.


## Deployment bootstrap

`scripts/bootstrap_isaac_vm.sh` installs the headless Python distribution into
`/opt/isaacsim` on a dedicated Ubuntu 24.04 GPU VM. Follow NVIDIA's
[Python installation guide](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_python.html)
for its license and compatibility requirements. Run it as root with a curated
server-only archive and an owner-only worker environment file as arguments. Never
bundle projects, local runtime credentials, or custom SDK drafts. The environment
must contain `ISAAC_WORKER_TOKEN`,
`ROBOT_IDE_ACTIVITY_DIR=/var/lib/robot-ide/activity`, and the applicable Isaac
license setting. Set `ROBOT_IDE_ALLOW_ROOM_UPLOADS=1` to accept room scene uploads.

The script installs services but does not start or enable them. Complete native
GPU validation and first-run shader warm-up before enabling the ten-minute
watchdog and worker with `systemctl enable --now robot-ide-idle-guard robot-ide-isaac`.
The provider's two-hour STOP limit must remain configured throughout setup.
This bootstrap does not install a remote desktop or the separate NuRec trainer. It uses a writable Kit portable root under `/var/lib/robot-ide/kit` while keeping the installed code root-owned. The first scene load can spend several minutes compiling RTX shaders; finish that warm-up before enabling normal idle shutdown.
If Google reports `ZONE_RESOURCE_POOL_EXHAUSTED`, the stopped VM cannot be
configured until GPU capacity is available. Retrying later preserves its disk;
moving zones requires a separate disk/VM migration.

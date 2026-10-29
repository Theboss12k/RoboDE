# Robot Workspace: the business app

`BUSINESS_APP/` is a separate React/Vite subproject. It uses the existing Python planning, validation, immutable revisions, resource ownership and execution engine. Its gateway exposes only the limited business API and read-only model assets; the full IDE has its own authenticated server gateway.

## Open it on a phone

From the repository root:

```sh
npm run business:build
npm run business:phone
```

Install [Cloudflare's official cloudflared binary](https://developers.cloudflare.com/tunnel/downloads/) first, either on PATH or as `SERVER_CLIENT/server/robot_system/runtime/tools/cloudflared`. The launcher starts the runtime if needed, a password-protected gateway, and a temporary HTTPS tunnel. It prints the URL and access code. A running older runtime must be restarted to load the new API. To see the current link/code or revoke access:

```sh
npm run business:phone:status
npm run business:phone:stop
```

Open the HTTPS URL on your phone, enter the code, choose the project, then **Room capture → New room capture → Open phone camera**. Allow camera access and take overlapping photos. Pause at each shot; keep roughly two-thirds overlap, fixed lens, steady lighting and several heights. Photos upload immediately to the server. Camera tracks stop when the camera closes, the room changes or you leave the page. You can also select JPG/PNG photos from the camera roll. Capture works without a GPU or cloud account. No video, depth measurements or metric floor plan are inferred by the camera alone.

The temporary link works while the server is running, the runtime/gateway are running, and the tunnel is connected. [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) have changing hostnames and no uptime guarantee. Use a named tunnel/domain or a separate small persistent web host for permanent access. The GPU VM should never host the only copy of the capture portal: stopping it must not prevent photo capture. Reverse-proxy upload limits apply; large imported USDZ packages may need direct administrator import rather than the temporary tunnel.

Access is protected by a random private code, signed eight-hour HttpOnly cookies, same-origin write checks, and login rate limiting. Owner-only connection/phone files and room photographs are excluded from Git. Restarting the gateway invalidates existing login cookies. The code grants access to all projects exposed by this single-operator installation; per-user tenancy/roles are not implemented. The existing runtime binds loopback; do not expose port 8765 directly.

## Give a command

Choose your workspace and use the named asset cards, 3D view, or touch floor plan. Type a command such as `MOVE APPLE FROM TABLE1 TO TABLE2`, or use **Speak** / the item-source-destination chooser. Voice recognition depends on the browser and may use its speech provider; it only edits the text. **Review command** compiles and validates a plan; **Start simulation** runs its exact revision. A workspace/configuration change makes the prepared revision stale. Stop-request feedback is distinct from confirmed stopped feedback.

Named objects and measured bounding boxes are read from the connected Isaac USD stage. Only tracked, configured objects can be used in planning; untracked native scene models are view-only. Browser geometry is simplified; the native Isaac viewport displays full USD/NuRec visuals. Surface transfers use the same atomic tasks and simulator as the IDE, with explicit `placement: on_surface`, support-face contact checking and final placement verification. Destination regions retain `placement: inside`. Unsupported robots/commands are rejected by the shared compiler.

For local development, run the Python runtime on 8765 and `npm run business:dev` (5174). `/business/` is also served from the Python runtime after a production build. Run `npm run business:test` for an isolated temporary test project; it never edits your saved project. Browser tests exercise the shared command flow, touch-size mobile layout, mocked camera capture and mocked speech recognition. Real phone permissions and native GPU behavior still need device acceptance.

## Reconstruct a captured room with NuRec

The separate GPU service in `SERVER_CLIENT/server/integrations/nurec/service.py` implements NVIDIA's [monocular COLMAP + 3DGUT workflow](https://docs.nvidia.com/nurec/robotics/neural_reconstruction_mono.html). Install NVIDIA's supported CUDA/3dgrut environment and COLMAP on the GPU VM, then install `SERVER_CLIENT/server/requirements-worker.txt` in that environment. Set:

```sh
cd /path/to/Robot_IDE/SERVER_CLIENT/server
export THREEDGRUT_ROOT=/opt/3dgrut
export NUREC_JOBS_ROOT=/data/nurec-jobs
export NUREC_WORKER_TOKEN=YOUR_RANDOM_SECRET_AT_LEAST_24_CHARACTERS
export ROBOT_IDE_ACTIVITY_DIR=/var/lib/robot-ide/activity
python -m integrations.nurec.service
```

The worker binds loopback port 9200 by default. Forward it alongside the Isaac worker on 9100. Set `NUREC_WORKER_URL=http://127.0.0.1:9200` and the matching `NUREC_WORKER_TOKEN` on the workspace runtime. Never put tokens in chat, repository files or the browser. Enable `ROBOT_IDE_ALLOW_ROOM_UPLOADS=1` on the managed Isaac worker to accept immutable checksum-pinned room packages.

After at least 12 photos, start the configured GPU if needed and select **Reconstruct room**. The authenticated worker serializes GPU jobs, runs COLMAP feature extraction/matching/mapping, trains 3DGUT, and exports USDZ. Jobs continue while the browser is closed. Cancellation terminates the subprocess group; shutdown/boot recovery marks interrupted jobs failed. Larger captures may exceed the configured maximum GPU session; that hard stop takes precedence over completing the job.

After reconstruction or an imported USDZ, calibrate metres per scan unit using a measured real distance, set translation/yaw to align the floor, and define named box proxies for tables, obstacles, destination regions and movable items. Review them in native Isaac, then **Use room in this workspace**. NuRec visuals do not create collision geometry or named semantic objects automatically. The package is referenced under a normal USDA root, with separate collision proxies; history stays immutable and configuration changes invalidate compiled plans.

Native COLMAP/3DGUT training, Gaussian rendering, PhysX contacts and cloud GPU availability are not validated by the local automated tests. Follow [GCP setup and shutdown safeguards](GCP_ISAAC.md) before activating cloud processing.

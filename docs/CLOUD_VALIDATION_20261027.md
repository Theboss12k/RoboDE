# Cloud release validation — 27 October 2026

The cloud IDE and Business App run against one persistent Linux backend and a separate native NVIDIA Isaac Sim 6.2.0 worker on the L4 VM `robot-ide-isaac-cloud / asia-south1-b / nvdiavm`.

| Check | Result |
| --- | --- |
| Runtime suite | 201 passed; one third-party Starlette/httpx deprecation warning |
| Business App browser suite | 8 passed, including phone layouts, permission failures and visible contextual errors |
| Electron suite | 2 passed; sandboxing, scoped file selection, execution and contextual errors |
| Production frontends | IDE and Business builds passed |
| Public cloud browser acceptance | Login, supplied logo, live native controls, reflected environment motion, Monaco, named USD inventory and shared Business/IDE feedback passed; no JavaScript exceptions |
| Public phone command | MOVE APPLE FROM TABLE1 TO TABLE2 completed all nine tasks in native physics |
| Native worker acceptance | Two robots, motion, confirmed Stop, reset, dynamic/static object editing and authenticated mesh transfer passed |
| Native scheduler | Independent tasks on two robots executed concurrently and passed |
| Persistent storage | Project cloning, compilation, execution and history passed through symlinked persistent project storage |
| Startup | `npm run cloud:start` and actual Electron GPU/status/Open cloud IDE path passed |
| Credit safeguards | Independent 600-second guard healthy; provider STOP after 7200 seconds; automatic restart disabled |
| Original local projects | SHA-256 comparison: all 146 original files unchanged |

The final native transfer was measured at `(0.27519, 0.26476, 0.05250)` metres, resting on Table2 at `(0.27, 0.27)`. Verification used native object feedback, not predicted positions or injected attachments. The demonstration was reset afterward; successful runs remain in its history.

Native testing exposed and corrected the educational gripper proxy's clear-aperture mapping, fingertip floor clearance and forearm overlap with its grasp area. Managed apple primitives now match the browser's spherical/ellipsoidal apple geometry. Native grasp verification allows 3 mm for the two authored 1 mm contact offsets and solver slop; raw joint-limit validation remains unchanged. Trajectory targets include bounded desired velocity feedforward; runtime motion remains force-driven. Failed contact runs were reported as failures and archived with the deployment acceptance workspaces.

Only the new VM runs. The previous VM in `asia-south1-c` remains stopped with its original disk. The temporary recovery snapshot was deleted. Both web entry points require the private team code; calculation and native worker ports bind to loopback. Services are enabled at boot. Cloud data is separate from the Mac's workspace, and persists across VM stops.

Private logs, screenshots and machine-readable results are in `artifacts/cloud-deployment-20261027/`, including `native-validation.json`, `native-transfer-validation.json`, `public-native-transfer.json`, `browser-result.json`, `electron-cloud-result.json` and `desktop-gpu-start.json`. Failed test projects were archived under `/var/lib/robot-ide-cloud/validation-archive-20261027/`; the original cloud projects were retained.

## Remaining boundaries

HTTPS Quick Tunnel addresses are temporary and may change after restart. One public workspace GET encountered a transient tunnel error during validation; a subsequent complete public acceptance passed. This deployment does not establish a permanent production hostname or availability guarantee. The websites stop with the VM and must be woken through the configured desktop host.

Automatic execution remains simulation-only. Demo assets are educational; arbitrary manufacturer robots need approved USD geometry and joint mappings. The browser renders observed Isaac state rather than a native Isaac editor/video stream. Room capture/upload is available, but the separate GPU NuRec reconstruction runtime is not installed. Physical live manual control and native camera/microphone capture on the user's phone were not exercised in this release.

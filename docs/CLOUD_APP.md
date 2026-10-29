# Cloud IDE and Business App

The React IDE, Business App, shared Python planner and NVIDIA Isaac Sim worker run on the GCP VM `robot-ide-isaac-cloud` in `nvdiavm / asia-south1-b`.

The Mac is needed to wake the stopped VM using its configured Google Cloud credentials. Once started, the public HTTPS applications run independently of the Mac. The browser is the interface; planning, inverse kinematics, compilation, execution and native physics run on the VM.

## Open a session

From the project directory on the configured Mac:

```sh
npm run cloud:start
```

This checks the provider STOP limit and independent idle guard, starts the VM if necessary, checks the protected applications, and prints their current HTTPS addresses. It does not start robot motion. Login uses the team access code saved in the owner-only file:

```text
SERVER_CLIENT/server/robot_system/runtime/connections/cloud-access.json
```

Use the `ide_url` or `business_url` from that file and enter its `access_code`. Do not commit this file or share it outside the intended team. Cloud phone access supports camera/microphone permissions over HTTPS.

The Electron/local IDE also exposes **Environment → Isaac Sim setup → Start GPU VM**, followed by **Open cloud IDE** and **Open cloud Business App**. Its GCP connection is configured for the new VM. The previous connection is backed up privately alongside it.

```sh
npm run cloud:status
```

Status is read-only and does not boot the VM. Session HTTPS addresses can change after a restart; use `cloud:start` to discover the current ones. The HTTPS entry points use [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), intended for temporary sessions. A stable production hostname requires configuring a named tunnel and DNS.

## Try the native demo

Select **Cloud table transfer demo** in either cloud app. In the Business App, enter **MOVE APPLE FROM TABLE1 TO TABLE2**, choose **Review command**, then **Start simulation**. The plan is decomposed into nine tasks and executed through the same planner and native Isaac worker used by the IDE. Inspect the named assets or live 3D view. Use **Reset simulator** in the IDE before repeating the transfer from Table1.

The demo was reset to its saved starting point after validation. Its successful run history is retained. The original Apple transfer and Dual arm cell projects are also available; failed deployment acceptance workspaces were archived outside the visible projects directory.

## Credit controls

- The guest stops the entire VM after **10 minutes without real work or active user interaction**. Background health, status and scene polls do not keep it awake.
- Explicit pointer/keyboard interaction sends a rate-limited activity acknowledgement. An unattended tab does not keep the VM running.
- Google Cloud enforces a **two-hour maximum per boot**, with termination action **STOP** and automatic restart disabled.
- Both cloud sites become unavailable when the VM stops. Wake it from the desktop IDE or `npm run cloud:start`.
- Closing a tab does not delete projects. Project files, imported assets, compiled revisions, provider configuration and execution history persist on disk.
- Stopped VM disks remain billable. The original `robot-ide-isaac` VM in `asia-south1-c` is retained, stopped, as a rollback copy. Only the new VM runs. No recurring automatic-start job or GPU reservation was added.

## Architecture and storage

| Component | Location |
| --- | --- |
| Cloud code and built frontends | `/opt/robot-ide-cloud` |
| Cloud Python environment | `/opt/robot-ide-cloud-env` |
| Persistent projects and runtime | `/var/lib/robot-ide-cloud/projects`, `/var/lib/robot-ide-cloud/runtime` |
| Private API | VM loopback port `8765` |
| Authenticated IDE and Business gateways | VM loopback ports `8083`, `8084` |
| Native Isaac worker | VM loopback port `9100`, separate process/Python environment |
| Access environment | `/etc/robot-ide/cloud.env`, root-owned, group-readable by the service account |
| Public session link discovery | `/var/lib/robot-ide-cloud/links.json` |
| Independent idle watchdog | `robot-ide-idle-guard.service`, 600 seconds |

Services run as the unprivileged `robotworker` account and are enabled at boot: `robot-ide-cloud-api`, `robot-ide-cloud-ide`, `robot-ide-cloud-business`, two protected HTTPS tunnel services and `robot-ide-cloud-links`. The native worker and independent root shutdown guard remain separate services. Calculations and worker ports are not exposed directly to the internet. Both web gateways require the team access code.

The initial cloud workspace was copied from the existing Mac projects and relevant runtime configuration. Subsequent cloud edits persist in the cloud workspace; they are not a bidirectional file sync with the Mac's separate local projects. The two cloud frontends share one backend and its ownership/scheduler. One native Isaac cell can be held by one project at a time; close manual controls and disconnect the previous environment before switching native projects.

## Updating the deployment

`SERVER_CLIENT/deploy/install-cloud.sh` installs code/frontend bundles and seeds the persistent workspace only when no cloud projects directory exists. Updating code does not overwrite existing cloud projects. It preserves the native worker token, installs the authenticated gateways, starts/enables the services and keeps the independent guard mandatory. Installation requires the configured OS Login administrator through SSH; no VM password is used.

The repeatable deployment artifacts and validation results for this installation are private under `artifacts/cloud-deployment-20261027/`.

## Boundaries

Automatic execution remains simulation-only. Real hardware still requires reviewed adapters and explicitly armed manual control. Manufacturer robots need an approved USD articulation and joint mapping; demo robot USD is educational geometry. The browser renders a simplified representation of observed Isaac state, not a native Isaac editor/video stream.

Room photo capture/upload is available through the Business App. GPU NuRec reconstruction is a separate service and is not installed by this deployment. Configure its approved reconstruction runtime and credentials before requesting room reconstruction.

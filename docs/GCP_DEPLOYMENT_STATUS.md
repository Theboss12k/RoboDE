# Robot IDE cloud deployment

Updated 27 October 2026 (India time). See [Cloud app operations](CLOUD_APP.md) for login, session startup, storage and updates.

| Setting | Active deployment |
| --- | --- |
| Project | `nvdiavm` |
| VM | `robot-ide-isaac-cloud` |
| Zone | `asia-south1-b` |
| Machine / GPU | `g2-standard-8` / NVIDIA L4, 23 GiB |
| OS / driver | Ubuntu 24.04 / NVIDIA 595.99.02 |
| Simulator | Isaac Sim 6.2.0, headless Python worker |
| Web applications | React IDE and Business App, authenticated HTTPS |
| Processing | Shared Python planning/runtime and native Isaac physics on the VM |
| Idle shutdown | 600 seconds without work or active user interaction |
| Maximum per boot | 7200 seconds, STOP, automatic restart disabled |

The previous VM `robot-ide-isaac` in `asia-south1-c` could not boot because L4 capacity was exhausted. Its disk was recovered to the new VM in `asia-south1-b`; the original remains stopped as a rollback copy. The temporary recovery snapshot was deleted. Only the new GPU VM runs. Retained disks remain billable while their VMs are stopped.

The Mac IDE now points to the new VM. It uses the existing dedicated SSH key and expiring OS Login registration. No VM password is used. Native worker, shutdown guard, cloud API, both authenticated web gateways and HTTPS tunnel services are enabled at boot. Both websites remain available independently of the Mac while the VM runs.

Use `npm run cloud:start` from the project directory to wake it and discover the current session addresses. Login details are in the owner-only runtime file `SERVER_CLIENT/server/robot_system/runtime/connections/cloud-access.json`. Session URLs can change after restart; they are temporary HTTPS tunnels, not a permanent production hostname.

Validated on the actual L4 VM:

- Native Isaac 6.2.0 scene transfer, two-robot joint motion and confirmed stopped feedback.
- Dynamic/static object editing, named live asset inventory and authenticated OBJ mesh transfer.
- Cloud compilation and concurrent execution of independent tasks on two robots.
- Full nine-task Apple transfer from Table1 to Table2, checked twice against observed native object poses, including through the public phone-sized Business App.
- Public HTTPS login, IDE manual controls with feedback reflected in the environment, Monaco code display, and phone-sized Business App command execution.
- Shared backend state between the two cloud frontends and persistent project cloning through external data-directory symlinks.
- Healthy independent 600-second guard and provider two-hour STOP limit. The original deployment also passed an actual automatic guest poweroff test.

Original Mac project data remains unchanged. Initial projects, history and relevant runtime configuration were copied privately into a separate persistent cloud workspace. Cloud edits do not automatically sync back to the Mac. Private deployment/validation evidence is under `artifacts/cloud-deployment-20261027/`.

Automatic execution remains simulation-only. Demo USD robot geometry is educational; manufacturer models require an approved USD articulation and joint mapping. The browser shows observed Isaac state through its simplified 3D renderer. Isaac native editor streaming and GPU NuRec reconstruction are separate services and are not installed. Room capture/upload remains available in the Business App.

## 28 October update

The global robot/adapter setup and offline capture import are deployed. The separate Linux installer was validated on the L4 VM with isolated data, both authenticated apps and native two-robot execution; temporary installer data was removed. Maintenance is complete and both VMs are stopped. The configured 600-second idle guard and 7200-second provider STOP cap remain enabled for future sessions. See [release validation](RELEASE_20261028.md).

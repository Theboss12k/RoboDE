# RoboDE 0.4.0 recording edition — delivery and validation

29 October 2026, India time. This is an additional recording-enabled edition of the existing shared Electron/browser IDE. Source, UI package versions and runtime health report 0.4.0. The title-bar badge reads the client package version instead of a hardcoded 0.3 label.

## Delivered

- Environment → Scene recording: native Isaac camera coordinates, resolution, fps, duration cap, Start/Stop, status, visible inline failures, worker-history recovery and MP4 download.
- Separate encoder process and bounded queue; native RGB rendering remains on the Kit main thread. Recording does not call the robot adapter or physics-step API. The temporary camera and its cleanup use the USD session layer, leaving the saved root scene unchanged.
- Existing lease ownership, robot Stop, concurrent plan/manual-control rules and VM shutdown protections remain active. Reset, disconnect, simulator switch, native starting-point replacement and room replacement reject active recordings before mutating the scene. Shutdown stops robot execution before waiting for bounded video export.
- Authenticated worker/API routes, project ownership validation, bounded MP4 copying to the runtime host, persisted history and checksummed downloads after the GPU worker is disconnected. The gateway preserves download filenames and integrity headers; the limited Business gateway does not expose the recording APIs.
- Real FFmpeg encoding is supplied through the pinned worker dependency or an operator-provided executable. No encoder download occurs on capture start. An older worker remains usable for simulation and explains the recording update requirement.
- Recording does not command motion. Existing native robot controls or a separately validated simulation provide motion while recording. The video excludes IDE overlays and audio.

The selected robot's editor stays above the recording panel. This preserves the existing drag/rotation interaction and keeps its controls near the scene. A bounded native acceptance script is available for a connected GPU scene; it refuses contract-test workers and does not boot a VM.

## Verification snapshot

| Check | Result and scope |
| --- | --- |
| Full Python runtime suite | **282 passed**, including recording worker, API, download and real FFmpeg tests using synthetic pixels. No native GPU rendering is implied. |
| Final camera/API checks after session-layer cleanup refinement | **20 passed**. Real USD camera transforms and session-layer cleanup are exercised with a fake renderer/annotator; native RTX still requires separate acceptance. |
| Full shared React browser suite | 31 passed initially, with one rotation test exposing the editor displacement. After moving the editor above the new panel, the focused recording/drag run passed **3/3**, covering the failed interaction and both recording cases. All 32 cases have passing coverage across those runs; this is not reported as one clean full rerun. |
| Hosted production browser suite | 22 passed initially; three existing access-code assertions failed because their global status locator also matched the underlying plan status. Assertions now target the access-settings region. The access-code cases plus compact layout passed **4/4** afterward. All 25 cases have passing coverage across those runs. |
| Electron | **4 passed** against isolated profiles and the production build: native recording panel, reviewed URDF import, trusted native picker, and saved-plan/dialog feedback behavior. |
| Production builds | Shared React IDE and Business App succeeded. IDE build retains the existing large Monaco bundle warning. |
| Installer archives | Four archives built with version/feature manifests, payload digests and archive SHA-256 files. Payload checks exclude runtime data, saved projects and credentials. Baseline archives verified byte-for-byte unchanged. |
| Local applications | Shared browser server and Electron relaunched; runtime reports 0.4.0, recording endpoints respond, and fingerprints of 15 saved project/connection/LLM configuration files are unchanged. |
| GCP state | Read-only provider verification confirms both configured Isaac VMs are **TERMINATED**. This feature work did not boot them or create another VM. |
| Native acceptance command | Correctly refuses the currently disconnected project with connection guidance; no VM startup or substitute capture occurs. Native camera capture remains pending an updated, available GPU worker. |

Python warnings retained: the installed FastAPI/Starlette test client reports a dependency deprecation; the intentional malformed ZIP fixture warns about a duplicate filename. Browser tooling also reports existing Three.Clock and terminal-color deprecations. These are separate from user-facing runtime failures, which the recording panel presents in place.

## Release files

`dist/releases/0.4.0-recording/` contains Linux/Windows × server/desktop installers, matching `.sha256` files and `release.json`. `dist/releases/0.3.0/` preserves the previous installers; `dist/installers/` is left unchanged. Existing installer upgrade behavior preserves user data and keeps separately identified code releases. This feature does not rebuild a signed macOS installer; the current macOS Electron source app continues to use its configured GPU VM.

See [Scene recording setup and worker upgrade](SCENE_RECORDING.md). Installing this local edition does not modify code on a stopped GCP VM. Deploy the recording worker edition and its requirements before using native capture there.

## Initial native GPU limitation (subsequently resolved for the L4 demo)

Earlier real startup attempts in both GCP zones failed with resource-pool exhaustion. No new startup was attempted for this implementation. Native RTX capture, first-render shader latency, camera framing/lighting, and capture performance alongside native motion remain unverified on those VMs. Synthetic fixtures remain explicitly labeled test sources and are not delivered as native simulation footage.

Once capacity is available, connect an updated worker, run the bounded native acceptance command from the setup guide, inspect its decoded frame/provenance report, then record a validated simulation to check motion. Existing idle shutdown and the provider's maximum-runtime STOP safeguard must remain enabled.


## Subsequent native L4 acceptance — 29 October 2026

The configured VM started on a later attempt. Recording code and FFmpeg were deployed with a backup of the preceding worker files. A real GPU test exposed an Isaac 6.2 annotator teardown issue: detaching RGB between recordings invalidated articulation views. The corrected implementation keeps at most one paused camera product per resolution for the loaded scene, reuses products between recordings, and tears them down only after stopping robot motion before scene replacement/shutdown. The startup lifecycle also retries an SSH forwarder that exits while the VM is still booting, within the existing bounded startup window.

The updated worker completed two consecutive capture/control/confirmed-Stop regression sequences. A separate 1280×720 / 10 fps recording captured an 18-task two-robot plan. All tasks completed using native observed feedback; execution finished `SIMULATION_PASSED`, with both robots confirmed stopped. The native file contains 426 frames over 42.6 seconds, no repeated frames, and a verified download checksum. This proves the demonstrated native scenario, not every GPU/robot/renderer combination or continuous collision certification. See [full demo evidence](NVIDIA_SCENE_RECORDING_DEMO_20261029.md).

The demo and recording were disconnected cleanly. The VM was explicitly stopped, with provider verification of `TERMINATED`, automatic restart disabled and the 7200-second STOP cap preserved. Public presentation artifacts contain no worker credentials. Previous capacity-failure recordings are retained as historical evidence; they are superseded by this actual native execution demo.


**Final native-fix suite:** 284 Python tests passed. The narrated 66.21-second H.264/AAC demo decoded fully, as did the 42.6-second original native camera clip. Installer payloads were refreshed with the validated worker fix and versioned checksums; the pre-native-validation archives remain in a separate backup subfolder.

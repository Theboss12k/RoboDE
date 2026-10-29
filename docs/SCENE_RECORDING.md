# RoboDE 0.4.0 — recording-enabled edition

This edition adds **native NVIDIA Isaac Sim scene videos** to the shared Electron and browser IDE. It records camera RGB frames on the Isaac GPU host and exports H.264 MP4. It is separate from recording the IDE interface or streaming the full Isaac desktop. The limited Business App retains its existing features; engineering recording controls belong in the IDE.

## Record a scene

1. Open the project and **Environment**. Configure the local RTX host or GCP worker as usual, then select **NVIDIA Isaac Sim** and connect. Existing scene-transfer behavior is preserved.
2. In **Scene recording**, choose resolution, frame rate and a maximum duration. Start at **640×360 / 5 fps** to check a new GPU host. Higher settings increase rendering load.
3. Expand **Camera position and look-at point** to frame the robot. Coordinates are metres in the project's Z-up world. The default camera is at `(2, 2, 1.5)` and looks toward `(0, 0.5, 0.3)`.
4. Click **Start scene recording**. Use native joint controls, or switch to Plans and run a validated simulation. The background recording continues across workspace navigation. Recording itself never sends robot commands or calls the physics-step API.
5. Click **Stop recording**, or let the duration limit stop it. Wait for MP4 encoding and the automatic copy to the RoboDE backend. Then click **MP4** beside the finished recording. Browser downloads go to the browser's chosen download folder; Electron uses its download handling.

Recording does not start a VM when the panel is opened or when history is listed. Simulator reset, disconnect, backend switching and native scene replacement are blocked until active capture/export finishes. Robot Stop remains available and does not stop the recording. Object edits that preserve the native scene are allowed when existing robot/scene ownership rules permit them.

The video has no audio, IDE panels, selection arrows or browser overlays. The camera remains fixed during one recording. Native scene assets, materials and lighting determine its appearance. Scene names and assets continue to use the existing project/Isaac integration.

## Install or update the GPU worker

The application and worker must both contain this edition. Older workers display an update message and recording stays disabled; existing simulation remains compatible.

The RTX server and desktop installers in `dist/releases/0.4.0-recording/` include the updated worker and install its dependencies automatically. The preceding installers are preserved in `dist/releases/0.3.0/`; installation releases retain their existing separate data directory.

For an existing source deployment, first copy this edition's `SERVER_CLIENT/server` code to the GPU host using your usual authenticated deployment. Stop active robot plans and recording sessions before restarting the worker. From that directory, install dependencies using **the Isaac Sim 6.2 Python environment**, for example on a Linux installation with NVIDIA's launcher:

```sh
/opt/isaacsim/python.sh -m pip install -r requirements-worker.txt
```

Use your configured launcher's actual path; GCP installations that use `/opt/isaacsim/bin/python` should use that executable instead. Restart the existing authenticated worker service using the same token, loopback listener, managed scene source and idle guard. No new streaming port is required. Existing GCP SSH tunnels carry the recording requests and MP4 download.

`imageio-ffmpeg==0.6.0` supplies an FFmpeg executable in platform wheels. A host administrator can instead set `ISAAC_FFMPEG_BINARY` to an absolute, executable FFmpeg path built with `libx264`. No binary is downloaded when a recording starts. Encoder failures appear in the recording's status; detailed encoder stderr stays in its GPU-host `encoder.log`.

On macOS, the Electron/API/UI continue to run locally while rendering and encoding run on the configured supported GPU host. Isaac Sim does not run natively on this Mac. This change does not deploy an updated worker to a stopped VM automatically.

## Limits, recovery and storage

- One active camera recording per worker; 1–300 seconds, 5/10/15/30 fps, 640×360, 1280×720 or 1920×1080. Each video is limited to 256 MiB; the worker requires 512 MiB free at start and refuses new recordings after its 1 GiB archive threshold or 100 metadata entries. A final video may take the archive above 1 GiB by at most one video's limit. Host administrators archive/delete old recording folders to reclaim space.
- The encoder runs separately with a bounded frame queue. Backpressure, malformed camera data, storage limits and rendering that misses too many frame deadlines fail visibly rather than generating substitute robot motion. Repeated observed frames are counted in metadata. Recorded duration is encoded frame count divided by fps; first-render setup is excluded.
- A worker lease expires after its existing timeout (normally 20 seconds). RoboDE's background recorder polling renews the lease during bounded capture/export. Losing the runtime/session finalizes the capture on the worker. A worker crash marks unfinished files interrupted on its next start; partial files are never offered as completed MP4s. Native camera products are pooled per loaded scene and resolution (at most three), paused between recordings and destroyed after robot motion stops during scene unload or worker shutdown. This avoids Isaac 6.2 invalidating live articulation views during annotator teardown.
- **Recover worker history** reconnects to an already running, connected worker and retrieves project-owned records, including videos finalized after a lost connection. Recovery does not boot a VM. Downloaded videos remain available after disconnect or VM shutdown. Interrupted metadata can be replaced by the worker's final result on recovery.
- Worker files: `~/.local/share/robode/recordings/<record-id>/` by default, or the host's `ISAAC_RECORDINGS_DIR`. Runtime cache: the existing runtime directory under `recordings/<project-id>/`. Credentials are never written into exported metadata or video URLs. The Business gateway does not expose these engineering APIs.
- Existing idle shutdown and provider maximum-runtime STOP settings remain in force. Capture activity is bounded by its duration limit. Video download/history views do not keep the VM running indefinitely. Shader compilation, encoding or network failure cannot guarantee a finished video before an external VM stop.

## Validation and remaining native acceptance

This edition is implemented with local contract tests, real FFmpeg encoding from synthetic pixels, authenticated worker/API download tests and browser controls tests. Those tests alone do not certify native RTX rendering. A subsequent native demonstration on 29 October 2026 validated camera capture, consecutive recordings, joint control after capture and an 18-task two-robot run on a GCP NVIDIA L4 / Isaac Sim 6.2.0. See [native demo evidence](NVIDIA_SCENE_RECORDING_DEMO_20261029.md) and `RELEASE_0.4.0_RECORDING.md`.

On 29 October 2026 the configured GCP L4 VM and standby VM could not start because their zones reported resource-pool exhaustion. Both remained stopped after the preceding attempts. Later that day capacity was available: the recording worker update was deployed and the native demonstration completed. The VM was then explicitly stopped and provider status verified. The earlier capacity-limited walkthrough remains a historical artifact; the new native demo contains genuine rendered motion.

After the updated worker is available, connect a project in the IDE and use the bounded native acceptance command from this checkout:

```sh
node scripts/python.mjs -m scripts.validate_scene_recording --project YOUR_PROJECT_ID
```

It records the connected native scene, downloads the MP4, decodes it and writes a provenance report under `artifacts/native-scene-recording/`. It does not boot a VM or command robot movement. To demonstrate movement, run a separate validated simulation or use native simulator controls during capture.

The native implementation follows NVIDIA's [Replicator capture and annotator interfaces](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/replicator_tutorials/tutorial_replicator_getting_started.html). FFmpeg distribution behavior is described by the [imageio-ffmpeg project](https://github.com/imageio/imageio-ffmpeg).

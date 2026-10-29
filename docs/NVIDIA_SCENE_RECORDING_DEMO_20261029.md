# NVIDIA Isaac Sim native recording demo — 29 October 2026

The demo ran on the existing GCP NVIDIA L4 VM with **Isaac Sim 6.2.0**. Footage is from its native RGB camera and RoboDE's actual browser UI; no injected simulator or synthetic test frames were substituted.

## Videos

- [Narrated RoboDE workflow with native camera inset](../artifacts/walkthroughs/RoboDE-NVIDIA-Isaac-Sim-demo.mp4): **66.21 seconds**, 1920×1080, H.264/AAC, chaptered. Shows connection, camera setup, compilation, both robots executing, export and the verified shutdown outcome. The inset uses native footage from the same run with illustrative alignment, rather than a latency measurement.
- [Original native camera MP4](../artifacts/walkthroughs/RoboDE-NVIDIA-Isaac-Sim-native.mp4): **42.6 seconds**, 1280×720 / 10 fps, H.264, no audio or IDE overlays. This is the unmodified cached worker file, with the same SHA-256 as the authenticated download.
- [Sanitized capture and execution manifest](../artifacts/walkthroughs/RoboDE-NVIDIA-Isaac-Sim-demo.json): source run, task outcomes, format details, hashes and shutdown verification; no worker tokens or access codes.

## What ran

A separate `gcp_demo` project contained two educational articulated arms, an apple and two tables. The plan assigned **18 standardized actuator tasks**, nine to each robot: raise the shoulder/elbow, sweep base yaw in opposing directions, rotate the wrist and return to the starting configuration. Independent robot chains ran concurrently; each chain retained its dependencies. These were explicit joint commands rather than an LLM planning demonstration or an object-grasp task.

Compilation validated task assignments, dependencies, declared joint limits, sampled geometry and inter-robot proximity. Run **`984776e6d25c`** finished **`SIMULATION_PASSED`**; all 18 tasks were marked completed from native simulator observations. Maximum sampled base-yaw magnitude was **0.65001 rad**, confirming observed robot motion. Both robots reported stopped after execution. This validates the demonstrated native command/recording path, not physical hardware authorization or universal collision safety.

Native capture contains **426 frames**, **zero repeated frames**, and a checksum-verified local download. The cached video was downloaded again after VM shutdown to verify independence from the GPU host.

## GPU-discovered fixes

The first capture exposed an Isaac 6.2 teardown issue: detaching the RGB annotator invalidated live articulation views. Recording now pauses and reuses a bounded pool of scene-owned camera products, with final destruction after robot motion stops during scene unload/shutdown. Two successive native capture/control/confirmed-Stop sequences passed after the fix, followed by the 720p full demo. Local tests cover camera lifetime and teardown ordering. GPU startup also retries an SSH forwarder that exits while the machine is still booting, within the existing startup deadline.

The updated camera worker is deployed on the configured GCP VM with a rollback backup. The VM's worker shutdown timeout accommodates bounded recording export. The local edition and refreshed recording installers contain the fixes. Earlier pre-native-validation installer archives are preserved separately.

## Shutdown and privacy

The native project was disconnected after the recording was cached. The VM was explicitly stopped; provider verification confirmed **`TERMINATED`**. Both Isaac VMs were checked stopped afterward. The independent 600-second idle guard, 7200-second maximum-runtime STOP cap and disabled automatic restart remain configured. Retained storage is preserved.

Original project, connection and LLM configuration files were kept separate from the demo workspace. Detailed local evidence is in `artifacts/native-demo-20261029-174016`; that directory includes private connection state and is not a public deliverable. Share the videos and sanitized manifest above.

## Validation

- Full Python suite after the fixes: **284 passed**.
- Focused recording/worker/API/transfer/startup checks: **32 passed**; camera/scene subset **40 passed** in an earlier focused pass.
- Actual L4: native scene transfer, two consecutive capture/control/Stop regressions, 18-task concurrent execution, camera export, download integrity and explicit VM stop.
- Final narrated video and audio decoded fully; frame previews checked. Production browser/Electron coverage from the recording edition remains documented in [release validation](RELEASE_0.4.0_RECORDING.md).

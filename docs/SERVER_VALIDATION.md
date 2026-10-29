# Server/client delivery checks — 24 October 2026

The repository is now organized as `SERVER_CLIENT`, `BUSINESS_APP` and `ELECTRON_APP`. The React IDE is shared by browser and desktop; the Python runtime remains the single planning, IK, execution and robot-ownership authority.

Verified in this checkout:

- Backend on macOS: all 172 tests passed (169 existing tests plus three new gateway/server integration tests).
- Linux ARM64 container: 169 passed, three skipped because the optional native USD package is absent. Native Isaac/GPU behavior was not exercised.
- IDE browser workflows: all 24 scenarios passed across the initial run and targeted reruns after correcting a robot-model loading race and test teardown/output conflicts.
- Business browser workflows: three passed.
- Authenticated server browser workflows: two passed, including shared plans across two browsers, server compilation/execution, locally bundled Monaco, and LAN HTTP without `crypto.randomUUID`.
- Both React production builds passed. Vite reports a non-fatal large-bundle warning for the IDE/Monaco assets.
- The Linux production image built and served authenticated HTTP. Docker Compose mounts existing projects and private runtime state; the image uses curated example projects rather than copying saved projects or credentials.
- Electron opened the relocated production React interface and loaded the shared API.
- The hosted launcher's status, graceful stop and restart worked. Its calculation API remains bound to loopback.
- The existing protected phone URL was restored and authenticated project/frontend access checked.
- All 146 pre-existing saved project files still match the pre-relocation SHA-256 manifest. Disposable browser-test projects were removed.

Windows launch/setup paths and dependencies are provided; a native Windows machine was not available for execution. No GCP VM was created or started. Native GPU and physical robot acceptance remain separate checks.

Commands to repeat the checks from PROJECT:

```sh
npm test
npm run server:build
npm run business:build
npm run test:e2e
npm run server:test
npm run business:test
docker build -f SERVER_CLIENT/deploy/Dockerfile -t robot-ide-server .
```

Stop the production runtime before `test:e2e`, which starts its own development runtime on port 8765. The hosted and business browser suites use isolated temporary project stores and separate result directories.

## Electron local/GCP Isaac setup follow-up

- The backend suite now has **178 passing tests**, including local process readiness/identity, port conflicts, startup timeout/cancellation cleanup, secret redaction, macOS rejection, configuration locks and Windows batch command quoting.
- All five hosted browser tests passed: the two existing workflows plus GCP configuration without implicit VM boot, native-file-picker integration via a scoped mock, and local lifecycle/macOS guidance.
- The actual Electron sandbox/preload/IPC test passed with `npm run electron:test`. It exercises the native dialog handler with a stubbed dialog, rejects an unknown picker type and rejects a separate untrusted window.
- All 24 IDE browser scenarios passed across the full run and targeted reruns. The full run had one simulator timeout and one outdated GCP selector; the simulator rerun passed and the selector now identifies the SSH example explicitly.
- No cloud VM or native GPU simulator was started during these checks. Native Windows execution and native GPU acceptance still require a configured GPU host.


## Continuous controls and simulator hand-off — 25 October 2026

- The full macOS runtime suite passed **187 tests** after the control/transfer implementation and ownership-lock correction. Five additional regression cases then passed in a targeted run: a destination claimed during hand-off, and static GLB/glTF/OBJ/STL conversion. Current coverage is 192 distinct runtime tests.
- All **12 hosted browser scenarios** passed, including held-pointer movement in both views, coalescing under delayed responses, Stop/Revert cancellation, automatic tool IK, intermediate connected feedback, setup flows and two-way multi-robot scene transfer with unsaved object drafts. The final source formatting/tutorial text update does not change tested behavior.
- The sandboxed Electron IPC/file-picker scenario passed; the production React build passed with the existing bundle-size warning.
- Transfer tests use an explicitly labelled `contract_test` worker with `physics_available: false`; production refuses that worker as a native Isaac backend. Offline USD checks verify articulation construction and static mesh geometry, not PhysX contacts or GPU rendering.
- All **146 original saved project files** still match the pre-relocation SHA-256 manifest. Scene transfer tests use disposable project stores. No GCP resources were created or started. Native GPU/Windows acceptance remains pending a supported host.

Workers must update to this checkout and install `requirements-worker.txt` for automatic mesh transfer (`trimesh==5.2.0`). Use `--project-scene` for educational demo robots or an approved manufacturer `--asset-catalog`; fixed scenes are attach-only. Texture shaders/animation are not translated, and native mesh collision uses explicit bounding boxes.

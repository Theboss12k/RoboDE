# URDF import delivery validation — 29 October 2026

Implemented in the shared React IDE used by Electron and the server/browser application. The Business App consumes configured project robots and does not expose engineering imports.

## Results

| Check | Result | Scope |
| --- | --- | --- |
| Complete backend suite | 258 passed | Existing runtime, migration, planning, simulator, adapter, Business and new URDF contracts |
| Final targeted URDF suite | 23 passed | Includes one additional regression after the full suite: a non-root arm frame on the floor is still rejected |
| Complete shared IDE browser suite | 30 passed | New import/review/LLM/controls flows plus existing configuration, tasks, tutorial, scenes and execution |
| Hosted browser suite | 18 passed | Shared-team gateway, control feedback, handoff, layouts, contextual errors and welcome |
| Native macOS Electron suite | 3 passed | New reviewed URDF import/source retention, sandbox/file-picker boundaries and saved-plan execution |
| Business browser suite | 10 passed | Shared scene, touch/phone layout, capture/export, speech, permissions, contextual failures and welcome |
| Installer unit tests | 5 passed | Packaging, setup and runtime contracts |
| Real local Ollama | Passed with `phi4:14b` | Optional metadata suggestions; extracted mechanical values unchanged; no model registered by the smoke test |
| Production builds | Both passed | Shared IDE and Business App TypeScript/Vite builds |
| Installer payload verification | Four passed | Linux/Windows × server/desktop; whole-archive and every manifest file SHA-256 checked; importer and example included |

Counts describe separate suites/snapshots and should not be summed. The additional floor regression was first corrected to supply the required frame fixture fields, then passed with the final targeted suite. No runtime code changed after the full backend run.

Commands: `node scripts/python.mjs -m pytest -q`, `npx playwright test`, `npm run server:test`, `npm run electron:test`, `npm run business:test`, `npm run build`, `npm run business:build`, and `node scripts/python.mjs installers/build.py --skip-build`. Final targeted checks used `tests/integration/test_urdf_import.py` and `tests/unit/test_installers.py`.

## What was exercised

- Raw and packaged URDF upload, multi-URDF selection, retained package/relative mesh resolution and source download after draft deletion/backend restart.
- Required missing limits/rates, explicit initial-position review, read-only extracted values, review acknowledgment, inactive validation staging, atomic registration and duplicate-ID rejection.
- Rejected malformed XML, DTD/entities/xacro, invalid numbers/axes, cyclic/disconnected trees, unsupported joints and unsafe ZIP paths/symlinks/duplicates. Missing mesh references remain visible warnings and are not fetched.
- Advisory LLM output, explicit acceptance, documentation evidence, private internal prompt handling and rejection of invented mechanical fields/targets. The real Ollama response left undocumented manufacturer/command claims empty.
- Negative-axis end-effector IK through the isolated global adapter controls; known oblique-axis FK; actual compilation and simulated execution of an imported Cartesian robot without a gripper.
- Global adapter testing remains simulated and cannot arm hardware. Importing an unrelated library model does not change existing project assignments/state/fingerprints.
- Full-width and compact import screens were inspected visually. Alerts remain in the import/review region; tables scroll within their container. Screenshots are retained in `artifacts/urdf-import-*.png`.

## Integration fixes

1. Global template tests now expose bounded simulated joint/tool controls and the companion 3D preview.
2. Cartesian Move no longer requires a gripper actuator on generic robots.
3. Coincident anchored root frames no longer trigger false floor failures; non-root floor contact remains rejected.
4. Backend FK/IK and browser preview share normalized vector axes, including negative and oblique directions.

## Limits and remaining acceptance

The built-in preview uses kinematic links, not the original robot meshes or certified collision/dynamic geometry. Native URDF-to-USD conversion and validated Isaac articulation/catalog setup remain explicit external steps. No GPU VM was started for this delivery; no native Isaac, real hardware, ROS bridge deployment, NuRec reconstruction or Windows target-host installation was newly certified.

Existing advisories remain: lazy Monaco bundle size, upstream Three.js Clock deprecation, Starlette/httpx test-client deprecation and the deliberately malformed duplicate-ZIP test fixture warning. They do not indicate a failed build or robot-control acceptance.

The normal local server was restarted with the new backend/production assets after verifying no active project runs. Test projects, adapters and import models used isolated stores. Existing user projects were preserved. Installer archives are under `dist/installers/` with matching `.sha256` files.

See [usage and API](URDF_IMPORT.md), [sample URDF](../SERVER_CLIENT/server/examples/robots/bench_gantry.urdf) and the [full project timeline](PROJECT_TIMELINE.md).

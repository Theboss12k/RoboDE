# RoboDE — local verification of all three applications

Date: 30 October 2026 (Asia/Kolkata). This records the initial local QA snapshot before the final Planner/Converter consolidation. See [the simplified-flow verification](SIMPLE_PLANNING_20261030.md) for the subsequent UI and runtime changes.

## Application results

| Application / shared component | Result | Coverage |
| --- | --- | --- |
| Server-mode web IDE | 28 passed | Authentication, workspace access, robot setup and publication, controls, scene switching, inline warnings, layout, keyboard/focus and greeting |
| Electron desktop IDE | 4 passed | Native application launch, URDF import, scoped file/access-code APIs, sandbox restrictions, saved-plan simulation, errors and recording controls |
| Business App | 11 passed | Named workspace assets, command review/execution, voice input, room photo capture, phone layouts, permission failures, cloud-capacity messaging and branding |
| Python runtime and integration suite | 330 passed; 4 skipped | Planning, adapters, validation, workers, ownership/arming/Stop, persistence/migration, APIs, simulator contracts and installer contracts |
| Native Linux robotics worker | 4 passed separately | Real MoveIt/OMPL planning, numerical IK, unreachable targets, swept collision checking, unsupported geometry coverage, differential-drive Nav2 and staged mobile manipulation |
| TypeScript and production builds | Passed | Type checking, shared React IDE build and Business App build |
| Broader IDE workflow suite | 32 passed | Additional end-to-end workflows covering plans, imports, controls, recording, tutorials and execution history |

The four ordinary-suite skips are the opt-in native robotics tests; they passed in the separate local ARM64 Linux container run. This does not imply native NVIDIA Isaac GPU or robot hardware validation.

## Live local services

Authenticated page checks returned HTTP 200 and served the built module entry for the web IDE at port 8081 and Business App at port 8083. The shared runtime on port 8765 reported healthy, with hardware disabled, no cloud session and no Isaac connection.

The existing local Ollama profile, `phi4:14b`, passed an actual text inference through the running API. It returned the exact requested connection-test response in 39.1 seconds. This verifies the live provider connection; the automated LLM planning and adapter-generation cases additionally use controlled provider fixtures. It is not a new benchmark of every model or of real-model planning across every workflow.

## Test isolation and limitations

Browser and runtime suites used temporary workspaces, injected transports and mocked camera/microphone permissions where applicable. No physical device was contacted, no GCP VM was started and no cloud deployment or GitHub push was performed. Existing user application services were left running.

The standard workflow ports were occupied by another local process. The workflow runner therefore used a separate temporary backend on port 8878 and the allowed development origin on port 5174. An initial attempt on port 5175 was correctly rejected by the API's origin boundary; that harness attempt was stopped and excluded from product pass/fail totals. No production origin checks were weakened and no tracked test configuration was changed.

Not verified in this run: native NVIDIA Isaac GPU simulation/rendering/recording, native NUREC reconstruction, real vendor SDK/hardware execution, remote GCP deployment, and Windows/Linux installer execution on their target operating systems. Their local contracts and UI paths are covered where corresponding tests exist.

## Configuration and usability findings

The current local AI library contains a Phi-4 profile. Nemotron support and its example integration remain in the source; the previously configured GCP profiles are separate from this local workspace. This run did not install additional models or copy cloud configuration.

After this initial QA snapshot, the source included Simple/Expert modes and a robot-first five-step setup. The subsequent local consolidation adds automatic Planner → Converter generation, adjacent plan actions and clearer controls. Its implementation and final verification are documented separately; the baseline counts above are historical snapshots.

Expected non-blocking warnings were present: Starlette test-client deprecation, a deliberately duplicated ZIP member in a rejection test, upstream THREE.Clock deprecation, Playwright terminal-color environment warnings and the Monaco production chunk-size advisory. Builds completed successfully.

## Evidence

The evidence directory is `artifacts/qa-all-versions-20261030/`. It contains the final summary, live-service results and copied suite/build logs. Browser failure traces and layout screenshots are retained under the existing test-results/artifacts folders when produced.

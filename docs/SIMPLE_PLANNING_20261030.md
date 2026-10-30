# Simple planning workflow — 30 October 2026

This is a local source update on top of the existing Simple/Expert interface and five-step robot wizard. It is not a new published installer, GitHub push or cloud deployment.

## Everyday flow

**Project → Plans → Tasks** remains the data hierarchy. Create a plan, enter one instruction and select **Generate plan**. It calls the global Planner to produce tasks and explicit robot assignments, then calls the global Converter to resolve those tasks against each assigned robot’s approved function catalog. Both stages finish before execution. Clarification pauses the Converter; unsupported commands remain visible and unresolved.

Select a task to edit its instruction, robot, dependencies or calls. Commands can be removed or added directly through labelled fields from the assigned robot’s catalog. Manual calls are checked without invoking the LLM again. Regeneration requires explicit consent to replace existing tasks and manual edits.

**Validate plan** and **Run simulation** sit next to the instruction and generation controls. Validation compiles deterministic motion and applies the existing physical checker. Incomplete coverage blocks physical execution. Changes invalidate readiness; old reports are labelled outdated. Historical revisions and runs remain immutable.

## Setup and controls

- Global **AI Models** exposes two roles: **Planner** and **Converter**. Either role may use the workspace default or a different saved provider. Ollama, OpenAI-compatible endpoints, custom function providers and Nemotron model names remain supported. System prompts stay internal.
- Robot setup uses the Converter. Its normal flow is **Robot → Controls → Mapping → Test → Save**, including the simulator adapter derived from the robot model. Low-level authoring, per-task AI overrides and compatibility tools remain in Expert mode.
- A plan can let the Planner auto-assign project robots or limit generation to selected robots. Selecting robots does not reassign existing tasks. Explicit task assignments remain editable.
- **Robot controls** beside the plan opens the assigned robot’s joint/tool panel in Environment. The Robots workspace also exposes **Open robot controls**. Default testing remains simulated.
- NVIDIA Isaac Sim’s connection, scene synchronization, native recording and recorded playback were preserved. No native GPU validation was performed during this change.
- The shorter guided tutorial covers setup, Planner/Converter, tasks, controls, validation and Isaac modes, retaining keyboard navigation and reduced-motion handling.

## Compatibility

`PlanDefinition.allowed_robot_ids` is an additive field: older plans load with an empty list, meaning automatic assignment across project robots. Edits from older clients preserve the existing selection when they omit the field. Unknown or duplicate IDs fail validation. The Planner receives only selected robots and cannot return assignments outside that scope. Scope changes preserve existing task assignments and saved history.

Legacy role and task fields remain loadable. Existing project and run records are not rewritten. The old goal authoring tools are closed by default and available only as compatibility tools in Expert mode. New tasks use semantic instructions and the command catalog.

A task instruction or robot change clears unchanged old calls. Explicitly edited commands submitted with an instruction edit are retained and validated, fixing an issue where regeneration could otherwise overwrite the user’s manual call. Task edits invalidate binding fingerprints, compilation and validation readiness.

## Verification

| Check | Final result |
| --- | --- |
| Python runtime/integration suite | 348 passed; 4 native tests skipped in this run |
| Native Linux MoveIt/Nav2 worker | The 4 skipped native tests passed separately |
| Shared web IDE | 32 passed in a clean full run |
| Electron desktop | 4 passed |
| Business App | 11 passed |
| Broader IDE workflows | 30 passed in the full run; the remaining 2 passed after updating compatibility tests for semantic task creation and boot greeting dismissal |
| Final generation/layout smoke | 5 passed, including 1100/1512/1920-pixel layouts |
| TypeScript and production builds | Passed for the shared IDE and Business App |

The broader compatibility checks now load a saved standalone LLM task instead of creating one through the normal robot-task flow, and exercise manual actuator commands through the new catalog editor. The compiled direct-actuator command is confirmed to use the joint path, bypassing pose IK.

The standard and NVIDIA local runtimes were restarted while idle, preserving their editions and separate data roots. The desktop opened successfully against the authenticated standard local workspace. Authenticated page/module checks returned HTTP 200 for browser ports 8091 and 8081 and Business port 8083. Both runtimes reported no cloud deployment, no connected Isaac session and hardware disabled.

Evidence: `artifacts/simple-workflow/summary.json`, copied suite/build logs and UI screenshots. Non-blocking upstream warnings remain for the Starlette test client, THREE.Clock, terminal colors and the lazy Monaco bundle size. Automated provider cases use deterministic responses through the real custom LLM worker or controlled HTTP transports. They test the two-stage orchestration and command contracts; they are not an evaluation of a real model’s planning quality.

The run uses temporary workspaces and injected simulator transports. It does not contact hardware, boot GCP, deploy code or publish a release. Real MoveIt/Nav2 worker tests run separately in the local Linux container. Native Isaac GPU rendering/recording and physical hardware require their own validation.

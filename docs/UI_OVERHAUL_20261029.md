# Shared IDE UI overhaul — 29 October 2026

Applies to the local Electron IDE and server/browser IDE. Package versions remain 0.3.0; this is a development update, not a newly published release.

## Delivered

- A unified dark workspace skin in `SERVER_CLIENT/client/src/ui/workspace.css`: consistent surfaces, borders, spacing, readable typography, rounded fields and cards, and restrained blue selection accents.
- Aligned application header, robot emblem/wordmark, project explorer, workspace navigation, task inspector, setup dialogs, form rows and environment controls. Workspace badges show robot, object and plan counts; compact screens hide secondary badges to preserve room.
- Consistent primary, secondary, destructive and Stop buttons, with hover/pressed feedback, visible keyboard focus and explicit disabled states. Reduced-motion preferences disable cosmetic transitions; coarse-pointer targets retain larger controls.
- Plan toolbar wraps at compact desktop widths; disabled compilation/simulation controls explain prerequisites in their titles. Project and robot selections retain their existing behavior and explicit task assignments.
- Simulator setup stays first in Environment. Secondary room capture import is grouped with the environment editors, allowing the scene and simulator controls to lead the workspace.
- Keyboard containment, Escape handling through the current dialog's close action, and focus return to the opener. Nested adapter dialogs keep their own close action. Autofocused creation fields retain normal Enter/form submission behavior.
- Fixed a modal dismissal bug: clicking the backdrop previously bypassed Configuration's busy/session guard. Backdrop and Escape now invoke the permitted close action; busy imports/provider operations remain open. New plan/project close controls are disabled while submission is in progress.

## Validation

| Suite/check | Result |
| --- | --- |
| Shared IDE browser workflows | 30 passed |
| Hosted browser controls, errors, simulator handoff, welcome and layout | 22 passed |
| Native macOS Electron | 3 passed |
| Production IDE build | Passed TypeScript and Vite |
| Installer archives | All four Linux/Windows server/desktop payloads rebuilt and checksums verified |

The hosted suite includes four new checks: aligned workspaces/utilities at 1100×720, 1512×982 and 1920×1080; and dialog focus/busy-backdrop behavior. These four checks are included in the 22, not an additional result to sum.

The complete shared suite exercised global robot/adapter import, reviewed URDF conversion and testing, task CRUD/assignment, compilation, code/history, multi-robot simulation, Stop, physical adapter simulated transport, global LLM form/code setup, refinement, tutorial/keyboard navigation, 3D object imports, workspace overlays, robot dragging/rotation, joint/tool control, Revert and starting-point application. Hosted tests exercised continuous/intermediate feedback, coalescing, cancellation, worker failures, scene handoff and contextual alerts. Native tests exercised reviewed URDF import, sandbox/file-picker boundaries, compiled plan execution and dialog errors.

A source audit of shared IDE component buttons found click handlers or form-submit actions; the three buttons without click handlers are deliberate submit controls. Functional acceptance comes from the workflow tests, not the source audit alone. Provider, hardware and cloud behavior still depends on the configured integration; this UI review does not certify arbitrary robot hardware or start a GPU VM.

Visual review covered the three workspaces, global LLM setup and native adapter selection. Before/after and responsive screenshots are under `artifacts/ui-overhaul/`; the native import screenshot is `artifacts/urdf-import-electron.png`. Existing Monaco bundle-size and Three.js Clock advisories remain.

## Restart and data preservation

The normal browser server was restarted and verified healthy at `http://localhost:8081`. The normal RoboDE Electron process was stopped and relaunched against the same local backend, preserving one authority for project data and robot ownership.

Before/after hashes confirmed saved project settings, robot configurations, scene objects, plan definitions and run history were preserved. Test suites used isolated stores.

The Mac was locked during the final native computer-use inspection, so the live relaunched desktop window could not be visually inspected at that point. Its process was verified running; the native Electron tests and screenshots had already passed. No attempt was made to bypass the lock.

The Business App was not redesigned in this update; it retains its shared brand/theme and business-specific layout. Remote GCP deployments were not started or redeployed. Updated IDE assets are included in the rebuilt server/desktop installer bundles.

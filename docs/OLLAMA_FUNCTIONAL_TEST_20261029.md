# Real Ollama functionality test — 29 October 2026

**Result: 9 of 10 real-model scenarios passed. The final compound object-lift scenario failed safely.** All 47 focused regression checks passed.

The installed model is `phi4:14b` (14.7B, Q4_K_M); no model named `phi4b` was installed. Tests used the actual local Ollama service at `127.0.0.1:11434`, not canned model answers. There were 46 recorded Ollama requests including diagnostics and reruns. Requests and responses are retained in `artifacts/ollama-20261029/ollama-calls.json`.

## Results

| Version / scenario | Result | Verified behavior |
| --- | --- | --- |
| Browser/server IDE: documentation → SDK draft → review → test | Pass | Real Phi-4 command extraction and Python transport drafting; generated adapter passes simulated contract checks; its base command produces 0.12 rad feedback |
| Browser/server IDE: goal → tasks → compile → simulate | Pass | Base reaches 0.2 rad; gripper reaches 60%, represented as 0.048 m |
| Native macOS Electron: SDK generation and testing | Pass | Same documentation workflow and simulated command test in the sandboxed Electron app |
| Native macOS Electron: goal → tasks → execution | Pass | Generated tasks retain their selected LLM provider and execute to the expected joint state |
| Business App: natural-language review and execution | Pass | Phone-sized touch interface invokes Phi-4 through the shared engine and executes reviewed commands; adapter authoring remains in the IDE |
| Virtual adapter generation | Pass | Phi-4 documentation extraction produces a virtual adapter that passes review and transport contracts |
| Cartesian movement through IK | Pass | Tool reaches world position (0.35, -0.10, 0.30) m within the test tolerance of 2 mm |
| Pick up apple and hold it 30 cm above its original position | **Fail, rejected** | Final model draft attempted grasp at z=0.155 m while the apple center was z=0.065 m; compiler returned HTTP 422 before saving tasks or executing motion |
| Unreachable Cartesian target | Pass | A (50, 0, 50) m request is rejected; the editable plan remains unchanged |
| Unknown actuator | Pass | `tail_motor` is rejected; the planner does not substitute another actuator or execute anything |

An earlier object-lift draft did successfully reach z=0.365 m from z=0.065 m. Other prompt iterations generated the wrong distance or attempted to close an empty gripper instead of grasping. The final result is therefore a failure for this compound request, not a general certification of Phi-4's manipulation planning.

## Fixes made from these tests

- Accept one leading fenced JSON response with optional trailing explanation, while rejecting malformed or multiple fenced blocks and still validating the task schema. Standalone LLM answers remain unchanged.
- Extract a single fenced Python SDK draft before validating its syntax. Strengthen SDK instructions to produce an injected `Transport` interface, avoid invented feedback and mark undocumented vendor functions with `NotImplementedError`.
- Send a compact robot-task schema with required fields for each command type, rather than duplicate schemas containing unrelated LLM-task fields. This reduces local-model context use and removes misleading nullable defaults.
- Permit one bounded model-authored repair for JSON/schema errors. Unknown targets, units, limits and unreachable poses are still validated independently; these errors are not silently replaced or clamped.
- Ground explicit relative vertical object moves in observed object positions. For the tested request, the required final position is (0.34, -0.16, 0.365) m and the object must remain held.
- Independently check compiled object positions and held-object feedback before saving a generated draft or preparing a Business App command. Regression tests prove that a schema-valid 10 cm lift is rejected when the user requested 30 cm, in both APIs.

The relative-goal checker currently covers explicit, unambiguous vertical object lifts in centimetres or metres. It is not a general verifier of every natural-language goal. Phi-4 drafts still require review; a rejected compound task can be corrected in the task editor by moving the tool to the object center before the explicit grasp task.

## Configuration used

In Configuration → LLM adapters:

| Setting | Value |
| --- | --- |
| API base URL | `http://127.0.0.1:11434/v1` |
| Model | `phi4:14b` |
| Timeout | 300 seconds |
| Maximum output tokens | 4096 |
| API key | Empty for this local Ollama service |

The URL is resolved by the backend machine. A Windows/Linux server installation should use Ollama running on that server, or an endpoint reachable from that server. The Business App uses the backend's configured global default; IDE goals can select a provider explicitly. Tests configured a separate provider in isolated QA data and did not change the user's global default or library.

## Evidence and reproduction

- Final summary: `artifacts/ollama-20261029/summary.json`
- Interface results: `artifacts/ollama-20261029/ui-results.json`
- Capability results, including the failed draft: `artifacts/ollama-20261029/capability-results.json`
- Exported generated drafts: `artifacts/ollama-20261029/phi-4-browser-sdk.bundle.json` and `phi-4-electron-sdk.bundle.json`
- Screenshots: `artifacts/ollama-20261029/*-adapter.png` and `*-plan.png`
- Regression output: `artifacts/ollama-regression-tests.log` — 47 passed
- Earlier failed responses and test iterations are retained alongside the final results.

The opt-in scripts are `scripts/ollama_functional_server.py`, `scripts/ollama_functional_check.mjs`, and `scripts/ollama_capability_check.py`. The fixture serves isolated API/IDE/Business ports 18877–18879 and uses a transparent recording relay on 18880. It forwards the application request to local Ollama without substituting answers. Run the server with `node scripts/python.mjs -m scripts.ollama_functional_server`, then the UI checker with `node scripts/ollama_functional_check.mjs` and capability checker with `node scripts/python.mjs -m scripts.ollama_capability_check`. These are opt-in diagnostics, not part of the default test suite.

## Validation boundary

The server/cloud application was exercised through its production authenticated gateway on the local machine. Native Electron ran on macOS; Business App phone testing used Chromium touch emulation. No GCP VM was booted or remote deployment updated for these LLM tests, and native Isaac Sim, Windows/Linux hardware and real robot interfaces were not revalidated.

SDK documentation used a deliberately fictional Bench SDK contract for the demo arm. Physical adapters were tested through injected simulated transports only. SDK source remains a review-only draft and is not certified as a real vendor integration. The incomplete SDK's missing full-joint writer remains unimplemented, and live eligibility stays false.

The local runtime and installer bundles include the compatibility and validation fixes. QA projects and generated test adapters remain separate from saved user projects and the active production library.

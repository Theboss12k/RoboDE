# RoboDE local LLM evaluation — 30 October 2026

## Recommendation

**Use `phi4:14b` for both Planner and Converter for now.** It was the strongest of the three models with the current RoboDE prompts and native Ollama function adapter. It completed all three application movement scenarios, rejected an impossible request, generated a testable SDK adapter, and passed both isolated Converter tests.

This is a recommendation for reviewed local simulation. Phi-4 still failed two Planner cases: ambiguous repetition and a Cartesian instruction. None of the tested configurations passed every complete plan scenario. Defaults in your saved workspaces have **not** been changed.

| Tested model | Complete plan cases | Adapter generation/test | Converter-only cases | Decision |
|---|---:|---:|---:|---|
| **Phi-4 14B** `phi4:14b` | **4/6** | **1/1** | **2/2** | Recommended for both roles, with task review |
| Nemotron Mini 4B `nemotron-mini:4b` | 0/6 | 1/1 | 1/2 | Fast direct-actuator conversion; unsuitable as the default Planner in this configuration |
| Nemotron 3 Nano 4B Q4 `nemotron-3-nano:4b-q4_K_M` | 0/6 | 0/1 | 1/2 | Not recommended with the tested adapter/prompt configuration |

Counts are functional scenario checks, not a statistical accuracy estimate or a general ranking of these model families. The combined initial totals are Phi-4 **5/7**, Mini **1/7**, and Nano **0/7**; the adapter case is not a plan. Isolated Converter results are additional tests, not successful retries of failed plans.

## Exact new plans and observed responses

Times below are observed end-to-end seconds, including UI/API work, model loading, formatting repair when used, compilation and simulation when reached. A shorter failed run is not a speed win.

| Case and interface | Phi-4 14B | Nemotron Mini 4B | Nemotron Nano 4B Q4 |
|---|---|---|---|
| P1 · Electron · explicit robot and single joint | **Pass · 61.67s.** ARM ONE only; `set_base_yaw(value=0.04, unit="rad")`. Other joints and ARM TWO unchanged. | **Fail · 36.60s.** Repeated robot metadata instead of a task proposal; repair returned explanatory prose. | **Fail · 33.79s.** Asked unnecessary questions and put task fields at the proposal root; schema rejected both attempts. |
| P2 · normal web · sequential gripper and joint | **Pass · 61.62s.** Gripper 50% → 0.04m, then base yaw −0.03rad. | **Fail · 33.88s.** Wrong-shaped metadata/invalid JSON after repair. | **Fail · 33.84s.** Wrong-shaped proposal with extra root fields after repair. |
| P3 · Business App · two assigned robots | **Pass · 70.48s.** ARM ONE +0.02rad and ARM TWO −0.02rad; other actuators preserved. | **Fail · 63.78s.** Wrong-shaped/repeated robot data; invalid JSON. | **Fail · 119.22s.** Output exhausted the 4,096-token budget; worker rejected the partial answer. |
| P4 · missing waving duration/termination | **Fail · 44.21s.** Invented 10-second waving/waiting tasks instead of asking. | **Fail · 34.33s.** Invalid JSON; no correct clarification. | **Fail · 44.78s.** Invalid proposal shape; no accepted clarification. |
| P5 · physically unsupported unaided floating apple | **Pass · 32.31s.** Returned unsupported: neither arm can make an object levitate unaided. | **Fail · 34.63s.** Invalid JSON; rejection was parser protection, not demonstrated understanding. | **Fail · 17.94s.** Asked about apple/table state and lifting without gripping instead of identifying unsupported levitation. |
| P6 · Cartesian end-effector position | **Fail · 93.86s.** Planner emitted a pose command without required `position_unit=m`; both attempts rejected before Converter/execution. | **Fail · 34.63s.** Invalid JSON after repair. | **Fail · 17.80s.** Asked irrelevant grasp/object-verification questions; Converter blocked pending clarification. |

The instructions, unchanged across models, were:

1. **P1:** “Using ARM ONE only, set base_yaw to 0.04 rad. Keep shoulder, elbow, wrist, gripper and ARM TWO unchanged.”
2. **P2:** “On ARM ONE open parallel_gripper to 50 percent, then set base_yaw to -0.03 rad. ARM TWO must not move. Keep all other joints unchanged.”
3. **P3:** “Rotate ARM ONE base_yaw to 0.02 rad and ARM TWO base_yaw to -0.02 rad independently. Keep all other actuators unchanged.”
4. **P4:** “Keep ARM TWO waving while ARM ONE waits.”
5. **P5:** “Make the apple float unaided one metre above the table indefinitely. Do not hold, throw or attach it to a robot.”
6. **P6:** “Move ARM ONE parallel_gripper to world position x=0.30 m, y=-0.10 m, z=0.30 m. Keep its gripper opening unchanged and do not specify orientation. ARM TWO must remain unchanged.”

For P2, Phi-4 omitted explicit task dependencies. The compiler supplied the same-robot dependency, preserving execution order. For P3, both robot assignments and final states passed; this test did not assert a minimum amount of temporal overlap. Phi-4 sometimes wrapped its JSON in Markdown/explanatory text; RoboDE’s existing extraction accepted it. A pass does not mean strict raw-JSON compliance.

P4–P6 failures were not executed. In particular, the harness stopped after Phi-4 incorrectly accepted P4; it did not run the invented waving sequence.

## Converter tested independently

Planner failure can prevent a good Converter from being exercised. These tests supplied the **same predefined semantic task**, explicit ARM ONE assignment and no function calls, then invoked each real Converter. No Planner output or hand-written command was injected as a successful conversion.

| Task | Phi-4 14B | Mini 4B | Nano 4B Q4 |
|---|---|---|---|
| Set ARM ONE base yaw to 0.04rad; preserve everything else | **Pass · 14.36s** | **Pass · 4.21s** | **Pass · 6.95s** |
| Move ARM ONE tool to (0.30, −0.10, 0.30)m in world frame; preserve gripper and ARM TWO | **Pass · 24.00s** | **Fail · 6.74s** | **Fail · 9.85s** |

All three generated the correct `set_base_yaw` call for the direct task. For the Cartesian task, Phi-4 returned:

```json
{"calls":[{"function":"MOVE","arguments":{"target":"parallel_gripper","position":[0.30,-0.10,0.30],"frame":"world"}}]}
```

The compiled built-in simulation ended at **(0.300000, −0.100000, 0.300000)m**, independently checked by forward kinematics, with the gripper and ARM TWO unchanged and stopped feedback confirmed. The approved MOVE catalog supplies the position units; this function-call contract differs from the legacy pose-command contract that failed in P6.

Mini and Nano added unrequested actuator resets and gripper changes, plus unsupported MOVE arguments such as `base_frame`. The dispatcher rejected the complete binding before any of those calls were executed. Their direct-command speed does not justify making either the default Converter for general tasks on this evidence.

## Documentation-to-adapter test

Each model received the same fictional EvaluationSDK 1.0 documentation with five single-actuator writers, units/limits, `read_feedback`, `stop_motion` and `disconnect`. No SDK module or client factory was documented. The current generation flow uses LLM metadata extraction followed by a deterministic source template.

| Model | Result | Time |
|---|---|---:|
| Phi-4 14B | **Pass:** all five documented vendor methods retained; reviewed draft passed generated-driver tests through an injected simulated transport. | 38.63s |
| Mini 4B | **Pass:** all five documented vendor methods retained; same worker/transport contracts passed. | 11.72s |
| Nano 4B Q4 | **Fail:** vendor methods became `set_`; it invented `EvaluationSDK`/`Client`. Generation remained `needs_information`; no usable driver was published or tested. The response had an empty issue list, so that response did not explain the failure well. | 34.87s |

These are simulated driver-path results, not vendor SDK compatibility or hardware qualification. They are not comparable to the older GCP free-form source-generation benchmark.

## Configuration and limits of this comparison

- **Machine:** Apple M4 Pro, 24GiB unified memory, macOS ARM64; local Metal inference.
- **Runtime:** separate official Ollama **0.40.13**, loopback port 11435. Existing Ollama **0.12.3** on 11434 was preserved. Old runtime installed Mini but refused the Nano manifest; the new runtime installed Nano successfully.
- **Weights:** Phi-4 14B Q4_K_M: 9.05GB; Mini 4.2B Q4_K_M: 2.70GB; Nano 4.0B Q4_K_M: 2.84GB. Exact digests are in the evidence JSON. Phi-4 was observed at approximately 12.3GB loaded allocation with 16K context; this is one runtime observation, not a guaranteed minimum.
- **Function adapter:** bundled `ollama_nemotron.py`, standard independent `invoke(input, system_prompt)` worker. Temperature 0; 4,096 output-token limit; 300-second call timeout. Mini context 4,096; others 16,384. Nano thinking disabled; unsupported thinking flag omitted for Mini/Phi-4.
- **Structured output setting:** native provider `format`/schema constraints were **not requested** by this example function. Prompts requested the application JSON contracts and existing validation/one Planner formatting repair remained active. Results describe this exact configuration. A constrained-output configuration may behave differently; it has not been scored here. Ollama documents JSON/schema constraints in its [structured-output documentation](https://docs.ollama.com/capabilities/structured-outputs).
- **Scene:** two named demo arms, separate base placements, fixed initial joint states and the same apple/table/basket environment. Disposable projects; no saved production plans or selected providers were changed by the model runs.
- **Application coverage:** P1 used a real Electron window; P2 the normal React IDE; P3 the Business App command review and simulation buttons. Remaining cases used their shared backend APIs. The model calls were real local inference, not mocked responses.
- **Success checks:** exact robot/joint values, unchanged unrelated actuators, resolved calls, compilation/checker acceptance for simulation, successful execution and confirmed stopped feedback. Cartesian follow-up also checked independent FK. Invalid proposals and partial output were not executed or counted as correct safety understanding.
- **Scope:** built-in simulation only. Physical-check coverage is incomplete for hardware authorization in this fixture. No native Isaac GPU, physical robot, rover/mobile manipulator or VLM testing occurred. No GCP or Nebius VM was started.
- **Sampling:** one complete run per model/case, with the existing one formatting repair when applicable; no retry-until-pass, fallback model, or prompt tuning between scored models. Other local browser tests ran during portions of the comparison, so times are practical observations rather than a dedicated performance benchmark.
- **Excluded infrastructure attempt:** one Nano UI launch was started before the preceding model finished, then terminated. Its partial calls are explicitly excluded. Scores use the subsequent serial Nano run; the exclusion note is retained in the evidence.

## Evidence and repeatability

[Machine-readable results](evaluations/local-llms-20261030.json) contain all instructions, raw final model answers, generated tasks/calls, validation results, final states, errors, timings, exact models and exclusions. They exclude internal system-prompt text and credentials. Local screenshots and raw logs are in `artifacts/nemotron-local-20261030/`.

The repeatable harnesses are `scripts/local_model_evaluation_server.py`, `scripts/evaluate_local_llms.mjs` and `scripts/evaluate_local_converters.mjs`. Start an installed compatible local Ollama on the configured loopback port, start the disposable evaluation server, wait for its ready message, then run model evaluation **serially** followed by Converter evaluation. A fresh run should use a new artifact directory (`--output` on the server, matching `ROBO_EVALUATION_OUTPUT` on both runners); model profile IDs only live for that disposable server session. No application source prompts were edited for these results.

After scoring, the harness bootstrap was tightened so even the API module's default-app import uses disposable storage. A smoke run confirmed exactly four evaluation projects and clean shutdown, without making another model request. Both temporary evaluation services were stopped; the original Ollama service and user applications remain running. Downloaded weights and evidence were retained locally.

## Application and provider verification

- Full Python runtime suite: **353 passed, 4 native opt-in skips**. The 68 focused provider/role/edition checks are a subset, not an additional total.
- Electron browser suite: **4 passed**. Business App browser suite: **11 passed**.
- Normal web suite: initial run **32 passed, 1 failed** from Monaco service initialization while switching Simple/Expert setup. Fixed service registration before language initialization; targeted recheck **3 passed**; full post-fix suite **33 passed**.
- Shared IDE production build, Business build and TypeScript checks passed. The updated IDE build reports a large-chunk advisory; this is not a runtime test failure.
- Nebius Token Factory’s modular function worker, credential handling, model discovery and UI/role selection passed fixture tests. **Hosted Nebius model inference was not run:** no key is configured. Provider choice remains independent of the robot adapter, simulator and application edition.
- Final focused provider recheck: **14 passed**; evaluation scripts passed syntax checks and the revised disposable-server startup/shutdown smoke check passed.

The maintained change record is [PROJECT_TIMELINE.md](PROJECT_TIMELINE.md). This report is local evaluation evidence, not a cloud release or physical-hardware certification.

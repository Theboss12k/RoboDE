# Nemotron model evaluation — 29 October 2026

The GCP deployment now defaults to **Nemotron 3.5 Bolt E4B Q4_K_M**, served by Ollama on the same L4 VM as RoboDE. The cloud IDE and Business App share this default. Phi-4 remains available; Mini and both Nano variants are registered as **experimental** alternatives. Explicit LLM selections in existing tasks were preserved. Recompile affected saved plan revisions after this configuration change.

Bolt was the strongest tested **planning** model. It passed joint/gripper control, Cartesian IK, the 30 cm apple lift, the Business command and standalone LLM execution. **None of the four variants passed the complete documentation-to-adapter scenario or the SDK draft review. This deployment does not claim reliable automatic SDK integration.** Existing tested adapter templates and explicit custom controls remain separate from these LLM-generation failures.

## Environment and configuration

- Application: RoboDE 0.4.0; shared Python planning/execution engine, with the Nemotron function example added. The React client was rebuilt to wrap long adapter names and model tags; installers were not rebuilt.
- VM: `robot-ide-isaac-cloud`, `asia-south1-b`, `g2-standard-8`; NVIDIA L4, 23,034 MiB VRAM; driver 595.99.02; Ollama 0.40.13.
- Default tag: `nemotron-3.5-bolt:e4b-q4_K_M`; adapter name **Nemotron 3.5 Bolt E4B · GCP**.
- Protocol: RoboDE Python function; base URL `http://127.0.0.1:11434`, without `/v1`; no external inference API key.
- Temperature 0; output limit 4,096 tokens; Nano/Bolt context 16,384, Mini context 4,096. Nano/Bolt `think=false`; only final content is returned. Truncated and empty outputs are rejected.
- A private, versioned `strict_format_v1` instruction prefix is installed on the four Nemotron profiles. The task/compiler prompts remain internal. Public adapter configuration excludes that prefix. The benchmark contains the profile needed to reproduce the tests.
- Ollama is enabled at boot, listens only on loopback, caches the weights, allows one loaded model and one parallel request, and unloads after 60 seconds without inference. No additional VM was created.
- Verified that the independent **600-second idle shutdown** and GCP **7,200-second STOP** cap remain enabled. Automatic restart is disabled. Activity was recorded for actual downloads/tests, not passive health polling.

The [Nano tags](https://ollama.com/library/nemotron-3-nano/tags), [Mini tags](https://ollama.com/library/nemotron-mini/tags) and [Bolt tags](https://ollama.com/library/nemotron-3.5-bolt/tags) identify the downloaded variants. Nano Q4 and Q8 are two quantizations of the same 4B model, not two independently trained models. Explicit GGUF tags were used on Linux; MLX variants were not selected.

| Installed tag | Downloaded size, decimal GB | Full model digest |
| --- | ---: | --- |
| `nemotron-3.5-bolt:e4b-q4_K_M` | 7.909 GB | `69f2be39b309ade35ef04ee02507915f4cd839f6631e14425146cb6c9df3bd39` |
| `nemotron-3-nano:4b-q4_K_M` | 2.838 GB | `6cc467f054393a55e98a74098abde0c762ffb6d1d8cd64becf30458f38886197` |
| `nemotron-3-nano:4b-q8_0` | 4.234 GB | `c534497d032cbb62f7938b9f8f315e7236d798ca51bb60408c943bd884b12269` |
| `nemotron-mini:4b` | 2.697 GB | `ed76ab18784f5a01c9ec5b3c250e964d4f9c7a983e59ba041bb995f0fe2e8fb3` |

## Configured-profile results

There are **12 cases per variant, 48 cases total**. PASS means the stated assertion passed for this run; it is not a general reliability percentage. Three cases intentionally request invalid commands and pass when the request is rejected without saving tasks. The strongest model's final score is **9/12**, after the independent SDK source review described below.

| Variant | Cases passed after SDK review | Median warm model request |
| --- | ---: | ---: |
| Bolt E4B Q4 | 9/12 | 1.658 s |
| Nano 4B Q4 | 8/12 | 2.325 s |
| Nano 4B Q8 | 7/12 | 2.931 s |
| Mini 4B Q4 | 5/12 | 2.895 s |

Warm request medians exclude calls whose Ollama `load_duration` was at least one second. They mix different prompt/output lengths and include schema repairs, so they are observations rather than a standardized speed ranking. They exclude browser/network and compilation time. The JSON evidence contains per-case times, token counts, load durations, answers and finish reasons.

| Scenario | Bolt E4B Q4 | Nano 4B Q4 | Nano 4B Q8 | Mini 4B Q4 |
| --- | --- | --- | --- | --- |
| Standalone JSON + GPU inference | PASS | PASS | PASS | PASS |
| Direct joint + gripper control | PASS | PASS | PASS | FAIL |
| Cartesian pose through IK | PASS | PASS | FAIL | FAIL |
| Grasp and hold apple 30 cm higher | PASS | FAIL | FAIL | FAIL |
| Reject unreachable request | PASS | PASS | PASS | PASS |
| Reject unknown actuator | PASS | PASS | PASS | PASS |
| Reject joint-limit violation | PASS | PASS | PASS | PASS |
| Virtual adapter from documentation | FAIL | FAIL | FAIL | FAIL |
| Physical adapter from documentation | FAIL | FAIL | FAIL | FAIL |
| Business command through LLM + simulation | PASS | PASS | PASS | FAIL |
| SDK draft with existing controls + code review | FAIL | FAIL | FAIL | FAIL |
| Standalone LLM task execution | PASS | PASS | PASS | PASS |

Successful movement assertions checked the final state, not just an HTTP success or a simulation status: base yaw `0.2 rad`, gripper opening `0.048 m` for 60%, other actuators unchanged; Cartesian position within 2 mm; and apple position `(0.34, -0.16, 0.365) m`, still held after the lift. The Business test deliberately used a joint/gripper instruction that does not match the deterministic transfer shortcut, proving an actual LLM call. Standalone LLM execution stored model evidence and left the robot unchanged.

### Failures and important distinctions

- **All documentation-adapter cases failed validation.** Bolt used an unregistered placeholder actuator; Nano returned empty catalogs in the configured pass; Mini returned malformed catalogs. RoboDE returned HTTP 422 and did not activate those drafts.
- **All SDK source reviews failed.** The tested-template path successfully produced drafts and passed the injected simulated-transport contracts. Subsequent static inspection found that Bolt/Nano could issue a supported partial movement before rejecting an unsupported complete joint set. Mini invented a client interface or used an undocumented method signature. These SDK drafts were never imported, executed, connected to hardware or copied into the production library.
- The first harness version counted the simulated-contract success as a pass. The preserved raw evidence still shows those original passes. A separate `sdk_review_overlay` changes all four SDK verdicts to FAIL; the matrix and totals above use the stricter verdict. The reproducible harness now includes that static check before review/testing. This preserves the original observation instead of silently rewriting it.
- Nano Q4 failed the object lift by adding an unsupported tool orientation. Nano Q8 also failed that lift, and its configured Cartesian response hit the output-token limit after about 75 seconds; the adapter rejected the partial answer.
- Mini failed direct/gripper, Cartesian, lift and Business requests. In the earlier baseline it silently omitted the gripper movement even though the resulting plan was otherwise valid. The final-state assertion caught this. Schema validity alone does not prove that every natural-language goal was fulfilled.
- Rejection PASS means **no accepted/saved/executed plan**, not necessarily correct model understanding. Some invalid requests were blocked for a different error, such as an unsupported orientation or changed robot assignment. No fallback model, canned plan, clamping or substituted actuator was used to turn failures into successes.

SDK contract checks covered joint mappings, units, limits, complete joint sets, invalid numbers, simulated feedback and confirmed Stop. They test the injected simulator transport, **not** the vendor SDK draft. The additional AST review is conservative and fixture-specific; it does not certify arbitrary Python integrations.

## Baseline before the formatting profile

A first run used only the application's existing prompts: 10 cases per variant, **40 cases total**. SDK template drafting and standalone LLM task execution were added to the second round; do not compare the fractions as identical suites.

| Variant | Baseline cases passed |
| --- | ---: |
| Bolt E4B Q4 | 8/10 |
| Nano 4B Q4 | 7/10 |
| Nano 4B Q8 | 6/10 |
| Mini 4B Q4 | 4/10 |

The baseline adapter failures included `$parameter_angle` instead of `$angle`, unused parameters, malformed parameter lists and repeated recipe steps. Nano Q4's baseline lift missed the required orientation-unit pairing; Nano Q8 introduced invalid task fields. Bolt passed the lift in both rounds. One normal application formatting repair is allowed during task drafting; both attempts are retained. No retry-until-pass loop was used.

First observed small readiness calls were approximately Nano Q4 **61.415 s**, Mini **3.688 s**, Nano Q8 **4.260 s**, and Bolt **73.756 s**. These include different model/kernel loading states and are not averaged cold-start benchmarks. Later warm calls were much faster. CUDA activity and fully offloaded model-layer messages were observed. Ollama's Bolt `/api/ps` memory figure under-reported the process footprint relative to `nvidia-smi`; it is retained as telemetry, not a measured VRAM peak.

## Verification, scope and reproduction

**59 focused regression tests passed**, including the Nemotron function contract, truncation/error rejection, private-prompt forwarding, reasoning exclusion, smaller Mini context, SDK review checks, LLM configuration, generated/named adapters and Business planning. The production React build also passed; Vite retained its existing warning about the large, lazily loaded Monaco chunk. One existing third-party test warning remains: Starlette TestClient deprecates its `httpx` integration in favor of `httpx2`.

Authenticated public verification checks the saved default, model, native endpoint, Python function selection and a real inference through the cloud gateway. It also checks Business sign-in/project access and that the limited Business gateway does not expose the global adapter API. Adapter labels are checked for wrapping at 1,440 px and 820 px viewport widths, and the Monaco editor is checked after loading. The final machine-readable evidence records the result. The screenshot is local evidence under `artifacts/nemotron-20261029/nemotron-cloud-configuration.png`.

All robot-motion benchmark runs used **temporary built-in simulator projects**. Production verification used a text-only model probe. Existing user projects, physical connections and robot positions were not modified by the benchmark. Native Isaac GPU physics, live hardware, vision/audio capabilities, mobile capture, a full browser feature sweep and Windows/Linux installer execution were **not** retested in this model evaluation. Desktop and browser share the tested engine, but this is not a claim of three independent end-to-end application runs.

Larger Nemotron 30B/70B variants were **not run**: their listed GGUF weights alone approach or exceed this L4's capacity before simulator/runtime memory. No larger paid GPU was provisioned. See [Nano model sizes](https://ollama.com/library/nemotron-3-nano/tags) and [70B sizes](https://ollama.com/library/nemotron/tags).

Run from the repository root on a machine with Ollama and the backend dependencies installed:

```sh
ollama pull nemotron-3.5-bolt:e4b-q4_K_M
ollama pull nemotron-3-nano:4b-q4_K_M
ollama pull nemotron-3-nano:4b-q8_0
ollama pull nemotron-mini:4b
node scripts/python.mjs scripts/nemotron_benchmark.py --strict-format --output artifacts/nemotron-repeat
```

Omit `--strict-format` for the original application prompt profile. `--models` selects explicit installed tags; `--tests` selects named cases. Use a new output directory per run. The harness starts a loopback relay, creates temporary workspaces, records synthetic model answers and returns a nonzero exit code if any case fails. It never configures the production default or downloads weights. Current code applies the stricter SDK review during the run, so its SDK failure can occur before a simulated contract test; historical raw contract results remain preserved here.

To configure another deployment, import [the Nemotron adapter function](../SERVER_CLIENT/server/examples/llm/ollama_nemotron.py) through Configuration → LLM adapters → Paste adapter code. The Ollama address must be reachable from the **backend**. Normal plan review, compilation and adapter testing still apply. The active cloud profile and Phi-4 alternative can be selected in that same UI.

[Full synthetic results, SDK review overlay and deployment verification](evaluations/nemotron-20261029.json).

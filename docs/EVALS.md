# Eval suite

The eval suite measures the Planner → Converter pipeline the way RoboDE runs it. It runs an instruction through the real API (`decompose`, `bind-commands`, `compile`) and the built-in mock simulator, then grades the result with deterministic checks. Cases live in version control, so a prompt, schema or model change can be checked against the same cases before it ships.

It complements the dated benchmarks ([local LLM comparison](LLM_MODEL_COMPARISON_20261030.md), [Nemotron evaluation](NEMOTRON_MODEL_EVALUATION_20261029.md)). Those drive the whole UI once. The suite runs in seconds when replayed, takes part in `npm test`, and can block a regression.

## Run it

```sh
npm run eval -- --model phi4:14b                       # live, against Ollama at 127.0.0.1:11434
npm run eval -- --model phi4:14b --record              # live, and save the answers
npm run eval -- --model phi4:14b --replay --baseline   # offline: fail if any case scores below its baseline
npm run eval -- --model phi4:14b --update-baseline     # accept this run as the new baseline
```

- **Several models:** repeat `--model`.
- **Selected cases:** `--cases p1_single_joint,n2_joint_limit`.
- **Another Ollama, such as a tunnel to a GPU VM:** `--ollama-url`.
- **Live and record runs:** each case runs `--repeat` times (default 3).

Each run writes `results.json` and `summary.md` to `artifacts/evals/<timestamp>/`, or to `--output`. The summary shows:
- cases passed on every run
- run pass rate
- median case time
- median model-call time
- tokens per case
- how often the planner needed its one formatting repair

Results always say whether they came from real inference or a replay.

**Exit codes:**
- **0:** the run finished.
- **1:** a case fell below its baseline.
- **2:** the model server stopped answering.

The model server counts as unavailable when it stops answering, or when it answers with an HTTP error, such as Ollama's 500 for a model architecture its runtime can't load. Then the interrupted case is not graded, recorded or used as a baseline, because a refusal case would otherwise "pass" during an outage. Cases that finished before the outage are kept in the results. The [6 November report](EVAL_RESULTS_20261106.md) describes the failures that led to this rule (F3 and F7).

## What a run uses

- **Workspace:** a temporary one. ARM ONE and ARM TWO are demo arms in the `apple_transfer` scene (see [`evals/fixtures.py`](../evals/fixtures.py)). Saved projects, credentials and the environment provider are not loaded.
- **Model adapter:** the bundled [`ollama_nemotron.py`](../SERVER_CLIENT/server/examples/llm/ollama_nemotron.py), for both roles. Temperature 0, 4,096 output tokens, 300-second timeout.
- **Simulation:** the mock adapter only. No Isaac physics, cloud worker or hardware.
- **Token counts:** a loopback relay in front of Ollama records prompt and completion tokens and model load time for each call. The Python function adapter can't return them itself.

## Cases

Each file in [`evals/cases`](../evals/cases) is one case: an `instruction`, an optional list of predefined `tasks` (which skips the planner, to test the converter alone), and `expect`.

| Group | Cases | What they check |
| --- | --- | --- |
| Movement (`p1`–`p3`, `p6`) | Single joint, ordered gripper then joint, two robots, Cartesian move | Final joint values in simulation, untouched joints, the other robot unchanged. The Cartesian case is checked by independent forward kinematics. |
| Judgement (`p4`, `p5`) | Ambiguous waving, impossible floating apple | The planner asks a question or refuses, and creates no tasks |
| Converter only (`c1`, `c2`) | Joint and Cartesian tasks given directly | Correct calls with no extra arguments |
| Edge cases (`n1`–`n7`) | Degrees, joint limit, unknown robot, unknown actuator, repeat count, named second robot, pick and place | Unit conversion; refusing what can't be done; exact repetition; no drift to the wrong robot; explicit GRASP and RELEASE |

`expect` keys:

| Key | Passes when |
| --- | --- |
| `status` | The planner returns this status: `ready`, `needs_clarification` or `unsupported` |
| `no_tasks` | No tasks were created |
| `bound` | The converter bound every task without errors |
| `blocked` | The request was refused, so no executable plan resulted. The planner, converter or compiler may refuse; the case passes whichever does. A pipeline error, such as malformed JSON, fails the case: it isn't a refusal. |
| `robots_used` | Tasks went to exactly these robots |
| `robots_unchanged` | These robots ended where they started |
| `final_state` | The listed joints ended at these values, optionally `{value, tol}` |
| `unchanged_joints` | The listed joints kept their starting values |
| `tool_position` | Forward kinematics puts the tool within `tol` metres of `position` |
| `min_calls` | At least `count` calls to any of the listed functions, counting a task's `repeat_count` |
| `required_functions` | These functions appear, optionally with exact arguments |
| `forbidden_functions` | None of these appear |
| `executed` | The simulation finished with confirmed stopped feedback |

`execute: true` compiles and simulates the plan. Cases that check final positions need it.

To add a case:
1. Add a YAML file whose name matches its `id`.
2. Run it live with `--record`.
3. Commit the case and its recording.

A recording is tied to the case's instruction and tasks. Changing either makes the replay stop with "stale" instead of grading old answers.

## Recordings and baselines

- **Recordings:** [`evals/recordings/<model>/<case>.json`](../evals/recordings) holds the model's final answers, timings and token counts for each run. It never holds system prompts.
- **Replay:** returns those answers in order. It stops if the pipeline asks for a different kind of call than was recorded.
- **Baselines:** [`evals/baselines/<model>.json`](../evals/baselines) holds each case's pass rate. `--baseline` exits with status 1 and names the case when any pass rate falls.
- **Updating a baseline:** only with `--update-baseline`, after the change has been reviewed.
- **Regrading:** after a grader change, `--replay --update-baseline` regrades the saved answers. The baseline keeps the model digest and Ollama version of the recording, marked `regraded_by: replay`.

`tests/evals/test_eval_suite.py` replays hand-written good and bad answers through the real API. This proves the graders catch:
- the other robot moving
- wrong values
- invented tasks for an ambiguous request
- out-of-limit values
- unsupported MOVE arguments
- stale recordings
- a planner crash counted as a refusal

## Limits

- **Simulation:** passes are mock-simulation results, not Isaac physics or hardware.
- **Statistics:** pass rates over three runs are observations of this configuration, not reliability figures. Temperature 0 makes most repeats identical.
- **Pick and place:** the case checks the calls, not the simulated grasp, because reaching the apple depends on the scene layout.
- **Configuration:** results depend on the Ollama version, quantization and adapter settings. Each report records them.

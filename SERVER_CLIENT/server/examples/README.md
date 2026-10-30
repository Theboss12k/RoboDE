# Examples: Project → Plans → Tasks

Every plan in `plans/` is a typed `PlanDefinition` containing atomic `TaskDefinition` records. Motion uses `operation: "command"` with an explicitly targeted `StandardCommand`; a pose uses IK, while a direct actuator/component target bypasses IK. All units are explicit. None of these examples author hardware-specific joint API calls.

| Example | Tasks and behavior |
| --- | --- |
| `joint_control` | Set `elbow` to -1.6 rad; verify joint feedback. No IK. |
| `gripper_control` | Set `parallel_gripper` to 50%, then 100% opening. No grasp is implied. |
| `wave` | Set `base_yaw` to 0.35, -0.35, then 0 rad; verify feedback. |
| `move_home` | One direct task per configured actuator, using its saved initial value and unit; verify feedback. |
| `apple_transfer` | Named-effector pose tasks plus explicit grasp, release and placement verification. |
| `lift_apple` | Approach, align, grasp and lift the apple 0.30 m; keep holding it. |
| `multi_robot` | Two explicitly assigned nine-task sequences; independent robots can overlap. |
| `multi_effector_pose` | Move `arm_2_gripper` on a two-tool Cartesian model using XYZ m / RPY rad, then set its opening. Other tool joints retain their state. |
| `llm_tasks` | Two standalone LLM tasks with dependency answer substitution; no actuator commands. Requires a configured provider. |

## Run offline examples

From the repository root:

```sh
npm run scenario -- --list
npm run scenario -- --example wave
npm run scenario -- --example joint_control
npm run scenario -- --example gripper_control
npm run scenario -- --example move_home
npm run scenario -- --example apple_transfer
npm run scenario -- --example lift_apple
npm run scenario -- --example multi_robot
npm run scenario -- --example multi_effector_pose
```

The runner copies the curated project/model fixtures into a temporary workspace, compiles through `compile_definition`, and executes the exact revision in the built-in simulator. It never connects to Isaac/hardware or resets saved project state. It can run while the desktop is open. Editable definitions, immutable revisions, snapshots, generated Python and run results are exported under `artifacts/examples/<example>/<run>/`; use `--output /absolute/folder` to select another output folder.

The `multi_effector_pose` fixture includes a complete fictional `dual_cartesian` model and an importable [model bundle](models/dual_cartesian.robot.json). Its tools have fixed orientation; the shown zero-RPY target is achievable. A different requested orientation can fail IK. Its built-in viewport uses a model marker; it is not a native manufacturer asset or grasp implementation.

Without `--example`, `npm run scenario` drafts the single-arm pick/place template. `--project dual_arm_cell` drafts its two default goals. `--prompt 'Move home.'` shows offline goal-to-task expansion. Other project IDs are copied into an isolated preview, and require compatible robot/scene definitions.

## Use the running IDE API

```sh
node scripts/python.mjs -m examples.run_plan --example wave --project apple_transfer
node scripts/python.mjs -m examples.run_plan --example wave --project apple_transfer --simulate
```

The first command creates a reviewable plan and immutable compiled revision. The second additionally starts simulation. The script uses the current measured state of the selected project, so robot IDs/models, object locations and placement must match the sample. Check Environment and reset explicitly if necessary. Compilation rejects incompatible or obstructed motion. API creation uses the new `/plan-definitions` endpoints; the revision ID and fingerprint identify the exact simulation.

To try the two-tool example in the IDE, import `models/dual_cartesian.robot.json` in Configuration, create a project instance named `gantry_01` using that model, then run the API client with `--example multi_effector_pose --project YOUR_PROJECT_ID`. Close controls before editing/importing; move conflicting scene objects/bases as needed. The sample intentionally contains no contact/grasp tasks.

## Test an adapter using the same standardized tasks

```sh
node scripts/python.mjs -m examples.test_adapter --project apple_transfer --robot arm_01 --adapter mock --example wave
node scripts/python.mjs -m examples.test_adapter --project apple_transfer --robot arm_01 --adapter YOUR_REVIEWED_ADAPTER_ID --example gripper_control
```

These clients always open **test** sessions: commands pass through the adapter's translation into injected simulated transport, and feedback is labeled simulated. Stop confirmation and session cleanup are explicit. Generated adapters must be reviewed and pass transport tests before standard command testing. The wizard's Wave recipe is derived from the same `plans/wave.json`; its lower-level bounded worker recipe is an internal transport representation.

## Standalone LLM tasks

After configuring a provider in the IDE:

```sh
npm run scenario -- --example llm_tasks --allow-llm
```

This explicitly contacts the configured provider. The runner reads its global profile without copying credentials into the temporary project or exported artifacts. The second task's input uses `{{tasks.describe.answer}}`. LLM answers are data, never joint commands. For the IDE API, `examples.run_plan --example llm_tasks` compiles using the selected project's configured default, and `--simulate` explicitly requests execution.

## Native Isaac Sim

The same command and plan formats apply to a validated Isaac scene. Start a GPU worker, load matching robot assets, and use the IDE's Environment native controls or the API client against that explicitly connected project. These offline examples validate the command/compiler/runtime contract, not native PhysX. See [GCP setup](../../../docs/GCP_ISAAC.md).

Existing historical revisions, run results and legacy compatibility tests retain their recorded format. New example generation uses the standardized task contract.

## Guided robot-import sample

See [Quickstart Gantry](imports/quickstart_gantry/README.md) for a self-contained visual URDF, a virtual-driver manifest, sample MOVE arguments, an environment OBJ and the step-by-step setup flow. The fixture is virtual and needs no manufacturer SDK.

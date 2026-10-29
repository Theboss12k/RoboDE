# Adapter generation and manual controls

Adapters have a **Physical** or **Virtual** target category. Controls are an interface for exercising either category. Robot SDK and ROS 2 are physical integrations; the built-in simulator and Isaac Sim are virtual integrations.

## Generate and test

Open **Robots → Adapters & controls → Generate adapter**. The setup flow is:

1. **Select target:** Physical robot or Virtual robot. The selected project instance supplies its registered model, limits and units.
2. **Choose method:** Use vendor documentation, or Define custom commands.
3. **Configure commands:** Select the physical SDK/ROS 2 interface or the virtual built-in/Isaac environment, then provide documentation or author simulator recipes. Joint mappings and remote unit conversion remain available.
4. **Generate:** create the complete adapter and command catalog as a draft.
5. **Review commands & adapter:** inspect supported/unavailable commands, parameters, recipes, mappings and source; record review against the exact bundle hash.
6. **Simulator test:** transport contracts run and an isolated built-in test window opens automatically. Select each command, set parameters and run it beside the 3D robot. Results include step progress, translated commands, simulated joint feedback and stopped confirmation. Stop cancels the remaining recipe; closing the window stops and disconnects it.

**Documentation method:** supply the SDK/API version and paste/import documentation text. Select any configured global LLM adapter. Extraction produces a catalog with vendor function/signature, a supporting documentation quote, typed parameters and a bounded simulator recipe. Missing/ambiguous APIs or tasks without simulation support stay explicitly unavailable. Physical SDK drafting also produces review-only SDK source. Documentation text is sent to the selected provider; documentation URLs are not fetched automatically. Configure an LLM in Configuration or use legacy `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY`.

**Custom method:** works offline for either target category. Define names/IDs, optional vendor bindings, bounded numeric parameters and recipes composed of Move joints, Increment joints, Set gripper, Wait, Read feedback and Stop. Recipe values are numbers or `$parameter` references, not Python/JavaScript expressions. Joint parameters use canonical model units; vendor degrees/mm conversion belongs to adapter joint mappings. Standard setpoints, initial pose, per-joint jog, gripper, feedback and stop commands are included automatically.

Draft bundles live in `SERVER_CLIENT/server/robot_system/runtime/adapter_drafts/<id>/`. They contain `bundle.json`, `adapter.py`, `controls.json`, `commands.json`, an executable `test_adapter.py`, and, for documentation-based SDK drafts, `sdk_transport.draft.py`. Exports include all source and command definitions. Command content participates in the review hash; modifying a recipe invalidates review. Reviewed bundles passing transport contracts receive a **test-only** registration. Older bundles without command catalogs retain their original controls and review hashes.

The separate adapter process executes the bounded generated joint translation and the fixed injectable adapter interface. It validates their AST/template before use. Arbitrary SDK draft code is **never imported or executed**, including during contract tests. This process boundary is not advertised as an arbitrary-code sandbox. The injectable fake transport records the translated command and decodes feedback; tests cover mappings, units, joint sets, limits, feedback and stop. A test pass is evidence about this transport contract, not vendor SDK correctness or physics.

Physical connection profiles belong to project robot instances in `robots/<instance>/connections.json`, rather than reusable BOT model configuration. The wizard creates a profile for a physical adapter. Its Controls panel can select and save profiles; editing an active profile is rejected. Profiles reference the reviewed adapter hash and store environment-variable names instead of secrets.

## Control targets

- **Simulated adapter test:** default for every adapter; isolated joint preview and injected transport. It requires no simulator worker or physical connection.
- **Connected project simulator:** virtual adapters only, matching the Environment backend. Commands follow validated sampled motion and hold exclusive cell ownership; they change actual simulation state, so recompile plans afterward.
- **Physical robot:** supported ROS 2 transport only. Connect reads joint feedback; Validate connection & stop claims the bridge and requires readiness and measured stopped feedback. Explicit arming lasts 30 seconds. Commands are limited to 0.15 rad / 0.01 m per joint per command. SDK drafts remain test-only.

Manual sessions expire after 15 seconds without UI polling/activity. Stop, disconnect, stale feedback, changed adapters and expired arming disarm live controls. Stop requested and measured stopped confirmation remain distinct. Stop failure retains ownership until stop can be confirmed. Plan execution and manual environment controls share cell ownership; live controls use bridge-reported stable device identity across project/URL aliases. The ROS bridge also enforces ownership across separate clients.

## Example: Virtual Wave

Choose **Virtual robot → Define custom commands → Built-in simulator** for the included demo arm. The custom editor's Wave is derived from the shared [Wave plan](../SERVER_CLIENT/server/examples/plans/wave.json). Its authored tasks use standardized commands:

```json
{
  "id": "wave",
  "project_id": "apple_transfer",
  "name": "Wave",
  "tasks": [
    {"id":"right","name":"Turn right","operation":"command","robot_id":"arm_01","dependencies":[],"command":{"type":"SET_ACTUATOR","target":"base_yaw","value":0.35,"unit":"rad"}},
    {"id":"left","name":"Turn left","operation":"command","robot_id":"arm_01","dependencies":["right"],"command":{"type":"SET_ACTUATOR","target":"base_yaw","value":-0.35,"unit":"rad"}},
    {"id":"centre","name":"Return to centre","operation":"command","robot_id":"arm_01","dependencies":["left"],"command":{"type":"SET_ACTUATOR","target":"base_yaw","value":0.0,"unit":"rad"}},
    {"id":"verify","name":"Verify final joint feedback","operation":"verify","robot_id":"arm_01","dependencies":["centre"]}
  ]
}
```

These direct actuator tasks bypass IK. The wizard converts the commands into its bounded internal worker recipe for per-command transport testing; plan authoring and `/standard-command` use the same explicit command targets and units.

Other joints keep their current positions. Generate, review, then **Test Wave**. Expect right → left → centre and a passed result with stopped feedback. Motion duration is increased when necessary to respect configured velocity/acceleration limits.

To parameterize a move, add `angle` with unit `rad`, min `-0.5`, max `0.5`, default `0.1`, then set a Move step's `base_yaw` value to `$angle`. The test window exposes that parameter as a bounded numeric input.

## Command test semantics and APIs

The entire recipe is validated before its first command: known actuators, exact parameter set, finite values, units, joint limits and bounded duration. Known kinematics also receives sampled table/trajectory checks in the isolated scene; models without verified geometry expose joint transport testing and a model marker. Recipes are capped at 16 steps / 60 seconds, with velocity/acceleration-aware quintic samples. This test scene does not implement contact grasp physics or external devices/sensors. Tasks needing an unavailable simulator stay unavailable until a meaningful implementation is defined.

Named recipes run only in `test` sessions, never live or connected-environment control sessions. Overlapping named commands and manual setpoints are rejected. Stop and disconnect cooperatively cancel the remaining steps, then request and verify stopped feedback. Per-command reports persist with the exact adapter hash, parameters, trace, scope and timestamps, and explicitly mark hardware as unvalidated. Core transport contracts and per-command results are separate evidence; a passing transport test does not claim every command has been individually exercised.

- `POST /api/projects/{project}/adapters/discover-commands`: selected provider + version/documentation → draft catalog.
- `POST /api/projects/{project}/adapters/generate`: accepts `target`, `configuration_method`, `commands`, optional `llm_adapter_id` and existing transport settings.
- `POST /api/controls/{session}/named-command`: `{ "command_id": "wave", "arguments": {} }` starts a monitored test and returns 202.
- `GET /api/controls/{session}` includes `command_run` progress/results; Stop and DELETE cancel and stop it.

## ROS 2 bridge

Run the bridge with a **ROS 2 Jazzy-enabled Python environment** on the controller host. The desktop Python environment does not need `rclpy`. Install FastAPI, Pydantic and Uvicorn in that ROS environment using the compatible environment's package management; ROS supplies `rclpy`, `sensor_msgs`, `trajectory_msgs` and `control_msgs`.

Create a JSON joint-limits file keyed by the controller's real joint names. Every entry needs finite `min`, `max`, positive `velocity` and `acceleration`, and `unit` (`rad` or `m`). Supply measured positions **and velocities**, with a current ROS timestamp, on the joint-state topic. Use a stable device ID shared by every bridge/profile connecting to that physical controller.

```sh
export ROS_BRIDGE_TOKEN='replace-with-your-own-long-random-token'
python -m integrations.ros2.bridge \
  --device-id manufacturer-controller-serial \
  --joints /absolute/path/controller-limits.json \
  --arm-action /joint_trajectory_controller/follow_joint_trajectory \
  --joint-states /joint_states
```

For a separate gripper trajectory controller, also supply `--gripper-action /gripper_controller/follow_joint_trajectory --gripper-joint gripper_joint_name`. This template expects **FollowJointTrajectory** for both controllers; other gripper action types need an additional transport integration. With no separate gripper action, all configured joints belong to the arm controller.

The bridge binds `127.0.0.1:8767` by default. Use an SSH tunnel for a remote host, and set the same `ROS_BRIDGE_TOKEN` in the desktop runtime environment. In the wizard/profile, set the bridge URL and token environment-variable name. Do not enter the secret itself into metadata.

The bridge uses monitored action goals, bounded trajectories, controller result/error checks, fresh feedback, cancellation and measured stop confirmation. A five-second bridge lease watchdog cancels outstanding work on lost clients. HTTP authorization, ownership and manual-control gates are contract-tested with fake controllers. **Actual ROS controller and physical hardware acceptance has not been performed on this Mac.** A cancel acknowledgement alone is not an emergency-stop guarantee.

Sources: [ROS 2 joint trajectory controller](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html), [FollowJointTrajectory contract](https://github.com/ros-controls/control_msgs/blob/master/control_msgs/action/FollowJointTrajectory.action).

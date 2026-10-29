# Task generation, IK and adapter execution

The hierarchy is **Project → Plans → Tasks**. A task describes one step; its command identifies what moves. “ROS action” remains the technical ROS protocol name.

## The actual LLM system prompt

Each invocation sends one system message containing the configured provider's global system prompt, followed by the IDE's purpose-specific prompt. The user's goal is a separate user message. For plan drafting, the IDE appends the selected robot's description, actuator/component IDs, canonical units and limits, named effectors, kinematic configuration, supported control schemes, observed joint feedback, current world objects and the exact task JSON schema.

The instruction is effectively:

```text
Decompose the goal into simple executable TASKS for the assigned robot.
Return {"tasks": [...]} as JSON, never code.
Use only the supplied actuators, components, named effectors and capabilities.
SET_ACTUATOR: exact actuator ID, value and configured unit; bypass IK.
SET_COMPONENT: exact component ID, opening percent 0..100; bypass IK.
MOVE_END_EFFECTOR: exact effector ID, XYZ metres, configured frame;
optional roll/pitch/yaw radians. The configured solver computes joints.
Do not invent joint solutions, sensors, geometry or unsupported operations.
Resolve relative requests against the observed world; 30 cm = 0.30 m.
Moving an object requires approach/grasp/lift, not just moving an empty tool.
Return an explicit error for unsupported or ambiguous requests.
```

The complete prompt is constructed in `SERVER_CLIENT/server/services/ai_orchestrator/task_drafting.py`. Prompt instructions alone are not the validator: schemas, explicit assignments, dependency validation, command units/ranges, IK convergence, joint/rate checks and available sampled geometry checks run before saving the LLM draft. The user reviews the editable tasks, compiles an immutable revision and explicitly starts simulation. No LLM response executes source code or physical hardware.

Without a configured LLM, the existing deterministic pick/place and move-home templates remain available. Standalone LLM tasks instead use their own task system prompt and input; their answers are recorded as data. Vendor-documentation adapter setup uses a separate extraction prompt requiring exact documentation evidence, bounded test recipes and explicit unavailable operations. Custom recipes such as Wave require no LLM at all.

## Standard command examples

Commands are structured data, rather than ambiguous function strings:

```json
{"type":"SET_COMPONENT","target":"parallel_gripper","value":50.0,"unit":"percent"}
```

```json
{"type":"SET_ACTUATOR","target":"elbow","value":-1.0,"unit":"rad"}
```

```json
{"type":"MOVE_END_EFFECTOR","target":"arm_2_gripper","position":[0.25,0.4,0.4],"position_unit":"m","frame":"world","orientation_rpy":[0.0,0.0,0.0],"orientation_unit":"rad"}
```

The last example uses `arm_2_gripper` from the complete [two-tool Cartesian model](../SERVER_CLIENT/server/examples/models/dual_cartesian.robot.json). Run it with `npm run scenario -- --example multi_effector_pose`. It is not a valid effector name for the demo arm. `SET_ACTUATOR` uses the configured ID `elbow`, rather than inventing a `MOVE_ELBOW_MOTOR` function per robot. A value of 40 is rejected if it exceeds the declared radian limits; degrees are not inferred.

For the educational demo robot, “move the apple 30 cm above its current position” can become Approach → Grasp apple → Lift apple. The lift task uses `MOVE_END_EFFECTOR`, target `parallel_gripper`, position `[0.34,-0.16,0.365]` m for the default apple pose. The gripper remains holding the apple; Release is added only if requested. Local grasps are idealized; native Isaac object movement must come from contact physics and measured poses.

## Robot configuration and IK

Reusable BOT definitions carry actuators, control schemes, adapters, kinematics and component mappings. Generated adapter bundles additionally include a hash-bound `standard_contract.json`; their existing joint mappings and scale conversion translate canonical joint targets to vendor/bridge units.

The demo arm retains its verified analytic position solver. It rejects explicit RPY targets because it does not provide a general orientation solver. `serial_chain_dls_v1` adds bounded numerical position/pose IK for ordered revolute/prismatic trees, including multiple branches and named effectors. Configure it in a robot bundle's kinematics:

```json
{
  "solver":"serial_chain_dls_v1", "world_frame":"world", "units":"m",
  "links":{"tool":0.01},
  "joints":[
    {"actuator":"slide_x","parent":"world","child":"x","axis":"x","type":"prismatic","origin":{"xyz":[0.0,0.0,0.2],"rpy":[0.0,0.0,0.0]}},
    {"actuator":"slide_y","parent":"x","child":"y","axis":"y","type":"prismatic"},
    {"actuator":"slide_z","parent":"y","child":"tool","axis":"z","type":"prismatic"}
  ],
  "end_effectors":{"tool_1":{"link":"tool","xyz":[0.0,0.0,0.0],"rpy":[0.0,0.0,0.0]}}
}
```

This Cartesian example requires three matching prismatic actuators and does not provide rotational DOFs. A six-dimensional pose is accepted only if its orientation is achievable. Joint origin transforms are applied before joint motion; axis is in the joint frame. Base placement supplies world translation/yaw. Only ancestors of the requested effector participate in IK, leaving other arms/components at their current positions. Component opening is configured in `capabilities.components`, for example `{"arm_2_gripper":{"actuator":"arm_2_finger","closed":0.0,"open":0.08}}`.

The solver checks limits and convergence, tries bounded seeds, and reports “target unreachable or no valid IK solution found.” It is not a collision planner and does not guarantee finding every feasible solution. Sampled link checks use configured joint origins; detailed mesh collision/self-collision is not certified. The built-in 3D robot rendering/workspace envelope remains demo-specific; arbitrary native geometry is viewed in Isaac Sim.

Direct joint/component tasks also work for configuration-only models without IK. Their validation reports that link geometry is unavailable, while retaining units, limits, velocity and acceleration checks. Unsupported object grasp models are rejected.

## Runtime interfaces

- Plans use `operation: "command"` and a `command` field for motion. Grasp/release/verify/LLM remain explicit atomic task types; legacy move records remain readable. Task object/destination references reserve shared resources separately from command arguments.
- The task inspector provides **Task type → Robot command task**, target selection, units and optional pose orientation.
- Adapter controls expose **Standardized task controls**. `POST /api/controls/{session}/standard-command` accepts the same structured command, resolves it, then uses the existing reviewed adapter's mapped transport, feedback, arming and ownership checks.
- Direct commands bypass IK. Pose commands are resolved into canonical joints before the adapter sees them. Automatic plans remain simulation-only; physical controls retain explicit arming.

All source examples, including API clients and isolated runner commands, are indexed in [examples](../SERVER_CLIENT/server/examples/README.md). Offline pick/place and move-home drafting now emits the same standardized task format as LLM drafting.

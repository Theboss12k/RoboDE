# RoboDE import sample — Quickstart Gantry

A fictional virtual XYZ robot with colored visual geometry, collision primitives and a tool marker. No external meshes, LLM, SDK installation or hardware connection is required. It moves its tool; it has no gripper and cannot pick objects up.

## Import the robot through the guided setup

1. Open **Configuration → Add robot · guided setup**. Choose **Virtual · simulator**.
2. At **Control adapter**, click **Use gantry template**, then **Review this driver revision** and **Test generated driver**. Continue after the tests pass.
   - Alternative: expand **Import / edit driver manifest**, paste the contents of `virtual_driver.json`, and click **Save driver draft**. Review and test it in the same way. This JSON is a driver manifest, not a robot-model file.
3. At **Import URDF**, choose `quickstart_gantry.urdf` and click **Read URDF**. Use global robot ID `quickstart_gantry` (choose another ID if it already exists). Select end-effector link `tool_tip`. Initial positions are all `0`. The file supplies position, speed and acceleration limits. Leave payload and gripper unset. Click **Validate robot definition**, tick the review checkbox, then **Save global robot & continue**.
4. Continue to **Map robot**. Map the joints below. Keep role independent, scale `1`, offset `0`, and tool ID `tool` on link `tool_tip` with zero XYZ/RPY offsets.

| URDF joint | Suggested alias | Adapter function | Units | Position range |
| --- | --- | --- | --- | --- |
| `slide_x` | Left / right | `set_slide_x` | m | -0.5 to 0.5 |
| `slide_y` | Front / back | `set_slide_y` | m | -0.5 to 0.5 |
| `slide_z` | Up / down | `set_slide_z` | m | 0 to 0.5 |

All three have a configured speed limit of 0.3 m/s and an illustrative acceleration limit of 0.8 m/s². The Y axis points toward negative world Y; a positive `slide_y` value decreases the tool's world Y coordinate.

5. At **Test actuators**, test each joint. Example values: `slide_x=0.10`, `slide_y=-0.05`, `slide_z=0.035`. Feedback is simulated.
6. At **Configure motion**, keep **STATIONARY**. The local Linux robotics worker enables MoveIt numerical IK and collision checking. Workspace bounds are optional. If you change settings and are returned to the actuator step, repeat the three tests for the new revision, then continue.
7. At **Test MOVE**, paste the contents of `move_example.json` and click **Compile & test MOVE**:

```json
{"target":"tool","position":[0.10,0.05,0.40],"frame":"world"}
```

The initial tool position is `[0, 0, 0.365]` metres. This MOVE should end near `slide_x=0.10`, `slide_y=-0.05`, `slide_z=0.035`.

8. Continue to **Publish**, review the configuration, then **Publish tested robot binding**.
9. In your project, open **Robots → Add robot instance** and select **Quickstart Gantry**. Save the instance, then select the published virtual mapping in **Reviewed robot & driver binding** and click **Save reviewed pairing**. **Test mapping in simulator** exercises the generated driver without hardware. Robot positioning and task assignment remain project-specific.

## Try a project plan

After adding this instance, select it explicitly in each task. With a planner LLM configured, an example instruction is:

> Move Quickstart Gantry's tool to world X 0.10 metres, Y 0.05 metres and Z 0.40 metres, then return the tool to world X 0, Y 0 and Z 0.365 metres. Do not move any other robot.

Without an LLM, add tasks with catalog functions. For each task choose `MOVE`, enter the relevant target/position/frame JSON above, save, and bind the manual calls before **Validate plan → Simulate**. The return task must depend on the first task. User-entered calls do not require an LLM provider.

## Optional environment asset

`sample_crate.obj` is a self-contained cube mesh. In **Environment → Import 3D object**, choose it, set the source up axis to Z, choose scene role Object, use longest dimension `0.05` metres and place it away from the robot (for example X `0.30`, Y `0.20`, Z `0.025`). Save the scene. This demonstrates visual object import; the sample robot has no grasping capability. Native physical checking of imported environment meshes currently needs reviewed collision representations and may return Incomplete.

## Optional LLM adapter-generation input

`virtual_sdk_manual.txt` documents only this fictional simulated SDK. You can paste it into vendor documentation to try LLM-assisted generation with target Virtual and version `robode-sim-v2`. Choose the provided template for a deterministic first run.

`validation.json` records checks run against this sample in a temporary workspace. It does not import anything into your saved projects. Native Isaac GPU and physical-hardware validation are separate and were not performed.

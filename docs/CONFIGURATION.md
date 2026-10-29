# Configuration, models and LLM functions

Open **Configuration** in the top bar at any time. Robot models and LLM adapters are global; project instances, plans and task selections belong to their projects.

## Workspace access

Open **Configuration → Workspace access → Show workspace access code**, then **Copy access code** to share browser IDE access with a trusted teammate. This is the server's shared IDE sign-in credential, separate from project IDs and the Business App's credentials. Browser users must already be signed in. The desktop's native **Workspace → Show workspace access code** menu works even before sign-in and includes **Copy code**; start the browser server once if no code exists yet. Installed desktops use their installation's access file.

The value is fetched only on request, is never stored in browser storage, and is hidden after one minute, when the document becomes hidden, or when leaving the panel. **Hide access code** clears it immediately. If browser clipboard access is unavailable, Copy selects the text for manual copying. The login page explains where to find the code without exposing it. The gateway returns access details only for a signed-in IDE session with caching disabled; the Business gateway has no such endpoint.

## Robot library

Export a registered model as a `.robot.json` template. The bundle contains `robot` identity, `actuators`, `kinematics`, `capabilities` and `initial_configuration`. Give an imported model a new lowercase ID. Import validates schemas, limits, units, actuator references and the initial configuration before atomically publishing the model. Definitions cannot import executable plugins or replace existing model IDs.

Use **Add robot to project** in Configuration, or **+** beside Project instances in Robots. Choose a registered model and configure the instance ID/name, initial joints and base placement. Existing measured simulation states remain unchanged. New instances start at their chosen initial joints. Native Isaac cells require separately deployed matching assets; change the project to the built-in simulator to change its robot set.

The included analytic planner supports the declared `analytic_yaw_two_link_v1` chain with the tested demo actuator names, axes and units. Imported models matching that contract can use different valid link dimensions and limits. Other models can be configured and tested through simulated joint transports, and appear as labeled markers in the scene. Direct standardized actuator/component tasks can compile without IK, with geometry limitations reported. End-effector pose tasks require configured analytic or serial-chain kinematics; arbitrary native geometry still requires its matching USD asset. The library also accepts reviewed URDF/mesh ZIP conversion; see [URDF import](URDF_IMPORT.md). Native USD conversion and vendor-driver installation remain separate.

Imported models persist in `SERVER_CLIENT/server/robot_system/runtime/imported_models/`. Export their definitions when moving a project to another installation.

## LLM adapter function

Each configured adapter resolves to the same async callable:

```python
async def explain_task(controller, adapter_id, task_description):
    invoke = controller.llm.adapter(adapter_id)
    result = await invoke(
        input=task_description,
        system_prompt="Explain this robot task concisely. Return text, not commands.",
    )
    return result["answer"]
```

Choose **Configure with UI** for a Chat Completions compatible API, or **Paste adapter code** for a trusted standard Python function in Monaco. Configure the API root, model, optional credentials, timeout and token limit. Prompt fields are hidden; the IDE supplies its instructions internally. The function posts to `<base_url>/chat/completions` with a system message and a user message, then extracts `choices[0].message.content`. Adapter and per-call system prompts are joined in that order. Results include answer text, adapter ID/version, model and numeric usage counters. Trusted custom Python LLM functions run in a separate cancellable worker with selected settings; this is not an OS sandbox. See [LLM adapters](LLM_ADAPTERS.md). Robot SDK draft execution is a separate, restricted workflow.

Multiple profiles can use different endpoints, accounts or models. Test each saved function directly in Configuration. These calls contact the configured provider. Choose a global default, or keep local templates for robot-goal drafting. Existing `AI_BASE_URL`, `AI_MODEL` and `AI_API_KEY` settings appear as an Environment provider for compatibility. Custom SDK drafting uses the global default function.

Saved credentials live in owner-only `SERVER_CLIENT/server/robot_system/runtime/llm/secrets.json` under an owner-only directory. They are excluded from public APIs, generated code, plan snapshots and run evidence. An API key environment variable can be used instead. Leaving the password field blank preserves an existing key; Clear stored key removes it.

### Task drafting

Goal generation has an adapter selector. Each atomic task also selects an adapter, with a global-default option. **Draft task refinement** sends the current task, available resources and your instruction through the chosen function. Only a schema-valid proposal with unchanged identity/dependencies is accepted. The result stays in the editor for review; Save and Compile remain explicit. Drafts cannot execute code or bypass motion validation.

### Standalone LLM tasks

Select **LLM task** as the task type. Supply input, an adapter and dependencies. Instructions are supplied internally. LLM tasks have no robot assignment or motion parameters. LLM-only plans issue no joint commands or physics steps and can run with configuration-only models. In mixed plans they are explicit cell synchronization barriers: earlier trajectories finish, robot commands pause while inference runs, then dependent tasks continue on the validated timeline. The timeline duration reports motion/sample time and excludes unpredictable provider latency.

Pass an earlier LLM answer with `{{tasks.<task_id>.answer}}` in the input. References must point to LLM tasks in the explicit dependency ancestry. Substitution is literal text replacement, never an expression evaluator. Answers remain data and cannot alter compiled trajectories.

Stop cancels an in-flight request and asks every simulator adapter to stop. Provider failure or an invalid response fails the run and stops the cell. Answers, provider/model versions and verification are saved with the exact run revision, visible in Simulation and Run history. Provider configuration changes require recompilation; historical answers remain unchanged. Profile edits/deletes are blocked during active runs and control sessions.

## APIs

- URDF draft/review/suggestion/source APIs: [URDF import API](URDF_IMPORT.md#api).
- `GET /api/registry`, `GET /api/registry/{model}/bundle`, `POST /api/registry/import`
- `POST /api/projects/{project}/robots` accepts `model_id`, `initial_positions`, `base_pose`, `id`, `name`.
- `GET/POST /api/llm/adapters`, `PUT/DELETE /api/llm/adapters/{id}`
- `PUT /api/llm/default` with `adapter_id` or null
- `POST /api/llm/adapters/{id}/invoke` with `input` and `system_prompt`
- `POST /api/projects/{project}/plan-definitions/{plan}/tasks/{task}/refine` with definition `version`, `instruction` and optional `adapter_id`

## Assign a task

1. Open **Plans** and create or select a plan.
2. Select **Add task**; select the new task in the list or project tree.
3. Choose its **Task type** and **Assigned robot** in the Task inspector.
4. Set motion targets, objects/destinations and **Wait for tasks** dependencies as needed.
5. **Save changes → Compile plan → Simulate**. Resolve compilation errors before running.

For pick/place instructions, **Generate tasks from goals** is the faster starting point: choose the robot for each goal, enter the instruction, generate, then review the resulting atomic tasks. LLM tasks choose an LLM adapter and have no robot assignment. Selecting a robot in Robots or in the workspace-view selector does not change a task's saved assignment.

The editable format is a `PlanDefinition` containing `tasks`. Each motion task uses `operation: "command"` and a typed `command`, rather than a nested task manifest containing nested steps. A pose task looks like:

```json
{
  "id": "lift",
  "name": "Lift apple by 30 cm",
  "operation": "command",
  "robot_id": "arm_01",
  "dependencies": ["grasp"],
  "object_id": "apple",
  "command": {
    "type": "MOVE_END_EFFECTOR",
    "target": "parallel_gripper",
    "position": [0.34, -0.16, 0.365],
    "position_unit": "m",
    "frame": "world"
  }
}
```

`robot_id` is an explicit assignment. `dependencies` orders tasks. `object_id` and `target_id` associate shared scene resources; they do not prove a grasp. The `command` describes the named effector and desired position; the configured IK solver supplies joints. Grasp, release and verification remain explicit atomic tasks because opening/closing a component alone cannot establish contact or object containment.

For a lift-only goal the destination association is unnecessary; the [complete lift example](../SERVER_CLIENT/server/examples/plans/lift_apple.json) retains the apple as a resource while holding it. [Pick/place](../SERVER_CLIENT/server/examples/plans/apple_transfer.json) ends with a verification task checking full bounding-box containment and an empty gripper. Generated revision code contains the immutable `TASKS` data plus a revision ID/fingerprint; historical manifests retain their original schema. See [all current example code](../SERVER_CLIENT/server/examples/README.md).

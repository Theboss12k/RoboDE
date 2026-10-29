# Architecture

## Project → Plans → Tasks

The three renderer workspaces own distinct concerns:

- **Robots:** shared BOT model configuration, project instances, initial joints, adapters, connection profiles and manual controls.
- **Environment:** built-in/Isaac backend connection, explicit reset, objects, obstacles, regions and base placement.
- **Plans:** stable editable plan definitions, atomic task assignments/parameters/dependencies, immutable compiled revisions, simulation runs and recorded evidence.

`PlanDefinition` has a stable ID, optimistic version, name, goal and `TaskDefinition[]`. A robot task contains one standardized command, grasp, release or verification operation assigned to one explicit project instance. Standalone LLM tasks have no robot assignment. Prompt goals are drafting inputs, not another persisted hierarchy layer. The compiler derives motion samples internally. Compiled `Plan` artifacts reference `definition_id` and `definition_version`; `Run` references both the definition and exact revision.

`SERVER_CLIENT/server/services/planning/definitions.py` validates assignments and dependencies, adds deterministic serialization for shared robots/objects/regions, constructs quintic sampled trajectories and merges them into one cell timeline including idle robots. Execution verifies atomic checkpoints before dependent tasks and rechecks final placement destinations after stopping. Offline goal drafting expands the versioned YAML templates into the same command-based task records used by the LLM. The older template/workflow compilers remain compatibility helpers for historical artifacts.

The included analytic FK/IK and viewport model remain specific to `demo_arm`. Registering metadata or generating a transport does not supply a verified geometric model, solver or manufacturer driver.

## Interfaces and execution boundary

`/api/projects/{project}/plan-definitions` provides definition creation/listing; its ID routes support optimistic updates, archive, goal drafting, compilation and revision listing. Existing `/plans/{revision}` and `/plans/{revision}/simulate` resolve immutable artifacts for compatibility and run history. Simulation rejects a changed definition version, changed configuration/state fingerprint, failed validation or conflicting resource owner.

`SERVER_CLIENT/server/services/api/configuration.py` separates shared model edits from world placement. Shared model edits back up previous files and validate all saved instances before acceptance. Saving initial joints never commands actual state. Explicit Environment reset initializes simulation. Environment disconnect retains last observed state as disconnected until explicit reconnect.

`SERVER_CLIENT/server/services/adapters` owns versioned generated bundles, exact-content review, contract tests in child workers, per-instance connection profiles, and manual sessions. SDK AI drafting is a separate code-proposal path from bounded task-intent inference. SDK drafts are never executed; only validated bounded translation and the fixed transport interface run in adapter child processes. See [adapter details](ADAPTERS.md).

Manual controls default to isolated simulated transport. Connected virtual controls share the plan controller's resource ownership. Live ROS 2 sessions use measured device identity, reviewed/tested adapter content, connection/stop validation, fresh feedback and explicit short-lived arming. A separate authenticated ROS-enabled bridge owns action execution and a lost-client watchdog. Automatic plan execution remains simulation-only.

Renderer Node integration is disabled. Electron uses context isolation and sandboxing. FastAPI binds loopback and checks Host/origin. The API accepts typed commands through validated control sessions, not arbitrary Python or SDK source. This is a single-user local developer runtime; it is not a multi-user network service.

## Persistence and migration

```text
projects/<project>/
  project.yaml
  robots/<instance>/instance.yaml
  robots/<instance>/connections.json
  environment/world.yaml
  plans/<plan>/definition.json
  plans/<plan>/revisions/<revision>/{plan.json,snapshot.json,generated.py}
  results/<run>.json
  migration_backups/v1/tasks/<legacy-revision>/...
```

Reading legacy `tasks/<id>` artifacts performs a repeatable copy migration. It backs up the original folder, preserves compiled artifact bytes and IDs, flattens legacy steps into editable tasks, and retains robot assignments/dependencies and run references. Archived definitions retain their revisions and remain resolvable through project run history. Compiled revisions cannot be overwritten.

Atomic JSON writes hold definitions, artifacts, profiles, adapter review/test evidence and simulation state. SQLite indexes run artifacts. YAML holds reusable models, project configuration, saved initial joints and scene setup. Fingerprints include current model/configuration, world and observed starting joint state. Editing definitions invalidates compilation through its version instead of changing historical artifacts.

On shutdown, active runs are cancelled and manual controls request stop. On restart, unfinished runs are failed with stop/completion unverified. Physical arming never persists. Reset is required before retrying a held object from an interrupted simulation.

## Isaac Sim and tutorial

The authenticated Isaac worker still owns a single cell lease and ordered complete-cell commands. Native Kit/PhysX operations run on the simulator's main thread. Only explicit reset initializes joints/object poses. Observed rigid-body poses determine outcomes; the controller never synthesizes native attachments. Native GPU acceptance remains separate from protocol and USD-structure tests.

The always-available tutorial visits the three workspaces, plan/task controls, all six generator stages, adapter control modes and execution history. Navigation is read-only; wizard previews never create a draft or connect a transport. Spotlights track DOM layout, transitions respect reduced motion, focus is trapped/restored, and Stop simulation remains available while the tour is open.

## Global configuration and asset imports

`SERVER_CLIENT/server/services/ai_orchestrator/llm.py` persists named provider profiles and resolves them to async `(input, system_prompt) -> result` functions. Goal drafting, task refinement, custom SDK drafting and standalone LLM tasks share this transport. Compiled standalone tasks pin provider IDs; public profile versions participate in project fingerprints. Secrets never enter snapshots. LLM tasks are cell barriers, with cancellation-aware requests and native worker lease refresh. Literal answer references are validated against dependency ancestry. Answers are saved as run evidence and never evaluated as motion or code.

`SERVER_CLIENT/server/services/api/model_library.py` imports declarative BOT bundles atomically into the local library. Instances explicitly reference selected models and validated initial values. Unsupported kinematics can be configured but cannot compile robot motion. Built-in visualization uses a labeled marker for models without verified geometry.

`SERVER_CLIENT/server/services/api/assets.py` validates and content-addresses project-local mesh assets. Scene drafts feed the viewport immediately; explicit world saves validate mesh references before persistence and state mutation. Three loaders handle bounded, self-contained geometry and dispose resources on unmount. Collision checks use declared bounding boxes. Project cloning copies referenced assets.

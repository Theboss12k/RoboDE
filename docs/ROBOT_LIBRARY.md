# Global robots, global adapters, project instances

**Configuration → Robot library → Add robot to library** is now the entry point for a reusable robot. It never adds an instance to the current project.

1. **Import robot information.** Choose a `.robot.json` definition, or start from an exported/template robot and give it a unique ID and name. The bundle contains identity, actuator limits and units, kinematics, capabilities and initial joint values. Review the editable JSON when adapting geometry; duplicating a template does not infer the new robot's dimensions.
2. **Review and save the robot.** Schema and model checks run before it enters the global library. Supported kinematics enables planning; other definitions remain configuration-only until a solver is integrated.
3. **Choose a control adapter.** Clearly select **Physical** or **Virtual**. Choose a compatible global adapter or generate one using SDK documentation / custom task recipes. Physical choices are Robot SDK and ROS 2; virtual choices are the built-in simulator and NVIDIA Isaac Sim. Generation and review no longer require a project robot.
4. **Review and test.** Generated drafts require review and transport contract tests. Library controls use an isolated built-in simulator and injected transport. Even a physical adapter's feedback is simulated here. Global tests cannot connect or arm hardware, and create no hidden/saved project.

Robot definitions and their compatible adapters are shared by every project **on the same installation/server**. Configuration has a separate **Control adapters** view. Existing built-in virtual templates remain available for each model. Changing shared limits invalidates adapter validation and affected compiled plans. Bundled model edits use a writable data copy; an installed release's source files are preserved.

## Add a project instance

In **Robots → Add robot instance**, select a global robot, name the instance, select the physical/virtual target and compatible adapter, then **Add instance & test**. The new instance opens its test panel. Initial joints and placement are optional advanced fields.

For an existing instance, select its adapter and **Save robot–adapter pairing**, then **Test selected adapter**. The pairing is stored in `robots/<id>/instance.yaml` as `control_adapter`, including the adapter's review hash. It persists across browser/device sessions; localStorage is no longer the source of truth for new pairings. Draft, stale, wrong-model and wrong-category adapters are rejected. Disconnect controls before changing a pairing.

Legacy instances without a saved binding continue to use the virtual built-in default. They are not rewritten automatically. Existing task robot assignments and historical runs are preserved. A binding change invalidates compiled plans through the instance snapshot.

The Environment workspace owns the actual simulation engine/connection and scene placement. A virtual instance binding does not silently switch the whole scene. A physical instance binding does not authorize automatic hardware execution: plans remain simulation-based; live manual control still requires a reviewed supported adapter, connection validation, fresh feedback and explicit arming.

## Import formats and boundaries

Robot import accepts declarative JSON and reviewed expanded URDF / mesh ZIP packages. [URDF import](URDF_IMPORT.md) parses structure and limits directly, requires configuration for missing fields, optionally requests metadata suggestions from a selected LLM, and retains source files for later Isaac import. It does not execute SDK plugins or xacro. Raw scene meshes and PDFs alone do not define a controllable robot. Manufacturer SDK documentation is used in the subsequent control-adapter step.

Original URDF meshes are retained, while the built-in preview renders the kinematic chain. Native USD/URDF visual and collision geometry must still be imported/approved in Isaac Sim separately with a matching joint mapping. Global library tests do not validate a manufacturer's native USD model or hardware behavior.

The server stores imported definitions under its private `runtime/imported_models`, adapter drafts under `runtime/adapter_drafts`, and reviewed/tested active adapters under `runtime/adapters`. Separate local and cloud installations have separate libraries; this change does not introduce automatic cross-machine file synchronization.

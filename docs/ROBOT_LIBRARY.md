# Global robots, global adapters, project instances

**Configuration → Robot library → Add robot to library** is now the entry point for a reusable robot. It never adds an instance to the current project.

## Add a robot with AI

**Configuration → Robot library → Add robot with AI** sets up a robot from its URDF (or a ZIP with meshes) and the vendor documentation, pasted or uploaded as a searchable PDF, Markdown or text file of up to 60,000 characters. Pick Virtual or Physical and an AI model, then **Configure with AI**. One job runs three stages and shows their progress:

1. **Read URDF and documentation.** Every review value is filled in, and each one records its source:
   - **URDF:** limits and speeds extracted from the file.
   - **Documented:** a value the AI model found in the documentation. Code checks that the quote occurs in the documentation and contains the number, converts the unit (for example 400 mm/s² to 0.4 m/s², or 115 deg/s² to 2.007 rad/s²), and checks it against the URDF. A rejected value is listed and the default stays.
   - **From URDF geometry:** the tool link, a gripper jaw (closed at its minimum, open at its maximum), and, for two parallel continuous joints on the root link, a differential drive with wheel radius, track width, footprint and top speeds.
   - **Default · review:** continuous-joint control windows of ±1000 rad, an acceleration that reaches full speed in 0.5 s, starting positions of zero (or the limit nearest zero), and a ±5 m drive area.
   - **AI wording:** the name and description.

   The robot ID is chosen so no saved robot uses it.
2. **Generate control adapter.** This is the documented driver generation described below. Without documentation, a simulator adapter with one function per joint is made when you accept; continuous joints get speed functions.
3. **Map joints to functions.** The AI model matches URDF joints to adapter functions by meaning. Code then sets each scale from the units (1000 for m to mm, 57.2958 for rad to deg) and checks every function, mode and range. Offsets stay 0.

**Review** is one page: every value with its source badge (hover to see the quote or reason), every problem at once, and editable fields. **Propose mapping again** retries a mapping step that failed. **Accept and build robot** checks the values (problems are marked next to their fields), saves the model, reviews and tests the adapter in simulation, and saves an unpublished mapping. A failed step can be retried without saving the robot twice.

**Try the functions** shows one card per mapped function, with the 3D preview. **Try every function** runs each one to its limits in turn; wheels spin both ways for 0.2 s. Each card shows the vendor call that was sent and the feedback. Mark each function **Works as expected** or **Wrong**. Marks are user observations stored with the setup draft, not test evidence. **Save robot** keeps the existing rules: the adapter reviewed and tested, every function tried, a passing MOVE test (which needs the robotics worker), and no function marked wrong. The same draft opens in the step-by-step wizard under **Resume setup**, which **Manual setup** also starts.

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

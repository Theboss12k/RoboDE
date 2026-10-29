import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  Square,
  X,
} from "lucide-react";
export type TutorialLocation = {
  workspace?: "robots" | "environment" | "plans";
  planTab?: "tasks" | "simulation" | "code" | "history";
  wizardStage?: number;
  connections?: boolean;
  configuration?: "robots" | "llm";
};
type TourStep = TutorialLocation & {
  title: string;
  section: string;
  target: string;
  fallback?: string;
  body: string;
  tip?: string;
};
export const tutorialSteps: TourStep[] = [
  {
    section: "Orientation",
    title: "Welcome to RoboDE",
    target: ".titlebar",
    body: "Your project contains plans, and each plan contains atomic tasks. Robot configuration and the environment have their own workspaces. This tour explains the controls without creating adapters, editing tasks or moving robots.",
    tip: "Use the arrow keys or buttons. Escape closes the tour; Tutorial opens it anytime.",
  },
  {
    section: "Workspace",
    title: "Three workspaces, three responsibilities",
    target: ".workspace-switcher",
    body: "Global Configuration manages reusable robots and adapters. Robots pairs them into project instances and opens their tests. Environment manages the simulator, objects and base placement. Plans manages goals, atomic tasks, compilation and execution.",
  },
  {
    section: "Workspace",
    title: "Choose or create a project",
    target: ".project-selector",
    body: "Choose a project here. The plus at the top creates one with separate instances, environment and plans. Reusable robot models remain shared across projects.",
  },
  {
    section: "Configuration",
    title: "Global robot library and LLM adapters",
    target: ".configuration-modal",
    configuration: "robots",
    body: "Configuration is available from the top bar. Add robot to library accepts a robot JSON bundle, a template, or an expanded URDF / ZIP with meshes. URDF import extracts exact joints and frames, marks missing limits for configuration, and offers optional LLM metadata suggestions. Review and validate before saving, then select a physical/virtual adapter and test in an isolated simulator. Nothing is added to the project here. Unsupported kinematics remains configuration-only until a verified solver is integrated.",
  },
  {
    section: "Configuration",
    title: "Configure multiple LLM functions",
    target: ".configuration-modal",
    configuration: "llm",
    body: "In LLM adapters, choose form setup or paste a standard Python adapter function, then save a name, API root, model and credentials. Add multiple adapters and choose a global default. Test the saved function with input to see its answer. The IDE supplies its instructions internally. Credentials stay in local owner-only files or environment variables; they are excluded from exported artifacts.",
  },
  {
    section: "Hierarchy",
    title: "Project → Plans → Tasks",
    target: ".project-hierarchy",
    workspace: "plans",
    body: "Expand a plan to see its tasks. Select a plan to edit its goal; select a task to inspect its robot, parameters and dependencies. The plus beside PLANS creates a named plan. Every generated task appears at this same task level.",
  },
  {
    section: "Robots",
    title: "Reusable models and project instances",
    target: ".robot-workspace-layout",
    workspace: "robots",
    body: "Choose a project instance on the left. Its model is reused across projects; its initial joint configuration belongs to this project. Selecting a robot here does not change task assignments.",
  },
  {
    section: "Robots",
    title: "Saved initial configuration",
    target: ".robot-editor",
    workspace: "robots",
    body: "A project instance pairs one global robot with one compatible global control adapter. Save robot–adapter pairing persists it on the server. Test selected adapter defaults to simulated transport. Initial joints and placement are edited in Environment.",
  },
  {
    section: "Robots",
    title: "Models, limits and capabilities",
    target: ".robot-editor",
    workspace: "robots",
    body: "Global configuration contains shared robot definitions, joint limits and compatible control adapters. Model edits invalidate affected compiled revisions and adapter validation. The included model is a fictional educational arm.",
  },
  {
    section: "Adapters",
    title: "Physical and virtual targets",
    target: ".robot-editor",
    workspace: "robots",
    body: "The target selector separates Physical targets, such as manufacturer SDKs and ROS 2, from Virtual targets, such as the built-in simulator and Isaac Sim. Controls are an interface for testing either category, rather than another adapter type.",
  },
  {
    section: "Generation",
    title: "First choose Physical or Virtual",
    target: ".adapter-wizard",
    workspace: "robots",
    wizardStage: 0,
    body: "First select the target: Physical robot or Virtual robot. The registered model is shown for reference and supplies joint names, limits and units. All initial command testing uses an isolated built-in simulator.",
  },
  {
    section: "Generation",
    title: "Vendor documentation or custom commands",
    target: ".adapter-choices",
    workspace: "robots",
    wizardStage: 1,
    body: "Use vendor documentation to draft commands with the selected LLM, or Define custom commands to author parameterized simulator recipes offline. The next step selects the physical SDK/ROS interface or virtual built-in/Isaac environment.",
  },
  {
    section: "Generation",
    title: "Documentation, mappings and connection settings",
    target: ".wizard-body",
    workspace: "robots",
    wizardStage: 2,
    body: "Configure the interface, name and joint mappings. Documentation mode needs an API version, official text and an LLM adapter; extraction returns supported commands with evidence and explicit unsupported entries. Custom mode combines moves, increments, gripper, waits, feedback and stop. Values use canonical model units and bounded numeric parameters.",
  },
  {
    section: "Generation",
    title: "Generate a reviewable bundle",
    target: ".wizard-body",
    workspace: "robots",
    wizardStage: 3,
    body: "Generate creates source, metadata, a transport interface, control descriptors, test artifacts and provenance. It creates a draft outside the active registry. Generation does not connect hardware or move a robot.",
  },
  {
    section: "Generation",
    title: "Review source before activation",
    target: ".wizard-body",
    workspace: "robots",
    wizardStage: 4,
    body: "Review the final command list, parameters, simulator recipes, mappings and adapter source. Review is bound to the exact bundle hash. Record review runs transport contracts and opens the simulator test window automatically. AI SDK source remains a draft and is never imported into the desktop/API process.",
  },
  {
    section: "Generation",
    title: "Test command translation and stop feedback",
    target: ".wizard-body",
    workspace: "robots",
    wizardStage: 5,
    body: "The test window connects to isolated simulated transport automatically. Select each named command, set its parameters and Test it beside the 3D robot. Progress, translation, feedback and per-command results are shown. Stop cancels the remaining recipe and confirms feedback; closing the window stops and disconnects it. Native Isaac physics and physical hardware need separate validation.",
  },
  {
    section: "Controls",
    title: "Every adapter has controls",
    target: ".robot-editor",
    workspace: "robots",
    body: "Open an adapter’s Controls button. Simulated adapter test is the default: sliders, number inputs, increment buttons and gripper controls update the simulator continuously through that adapter’s translation. Connected simulator previews show intermediate feedback while moving. Stop clears pending targets. The preview and feedback are labeled with their source; physical controls still require explicit arming and bounded commands.",
  },
  {
    section: "Controls",
    title: "Choose isolated testing or the project simulator",
    target: ".robot-editor",
    workspace: "robots",
    body: "Virtual adapters also offer Connected project simulator. It uses the simulator selected in Environment and owns that cell while connected. Isolated adapter tests use a separate preview. Disconnect controls before handing a shared simulator to a plan.",
  },
  {
    section: "Controls",
    title: "Validate, arm and stop live manual controls",
    target: ".robot-editor",
    workspace: "robots",
    body: "Reviewed and tested ROS 2 adapters offer physical manual control. Connect reads feedback; Validate connection & stop checks readiness and measured stop. Arming lasts 30 seconds. Missing feedback, disconnects or expiration clear arming. Stop requested and stopped confirmed remain separate.",
  },
  {
    section: "Environment",
    title: "Choose local or GCP Isaac Sim",
    target: ".isaac-connection",
    workspace: "environment",
    body: "Open NVIDIA Isaac Sim setup. On macOS, choose GCP GPU VM and configure the VM, token and on-demand shutdown safeguards. On a supported Windows/Linux NVIDIA GPU host, choose This computer, browse to the installed Isaac Python launcher, choose Automatic project scene and save. Select NVIDIA Isaac Sim to start the worker and transfer the scene automatically. Demo robots need no catalog; manufacturer robots need an approved USD and joint mapping once. Managed workers let Save scene add/remove objects. The native Isaac window opens locally or on the VM remote desktop. Native GPU acceptance remains separate from contract tests.",
  },
  {
    section: "Environment",
    title: "Choose the simulation backend",
    target: ".environment-toolbar",
    workspace: "environment",
    body: "Select the built-in simulator or NVIDIA Isaac Sim here. Switching automatically saves object drafts and transfers robots, placements, current joints and objects. Returning to built-in carries the observed scene back. Close controls and release held objects first. A failed transfer keeps the previous backend; an unreachable GPU fallback is clearly reported. Connect reads simulator state. Disconnect releases the connection. Reset simulator applies the saved initial scene. Simulator selection belongs to Environment, not individual task editing.",
  },
  {
    section: "Environment",
    title: "Explore the world",
    target: ".environment-scene",
    workspace: "environment",
    body: "The viewport shows all project robots, objects, destination regions and obstacles. Drag empty space to orbit and scroll to zoom. Click a robot or its name to open virtual controls. Drag its body to relocate it on the ground. Grid and Reset camera change the view. Coordinates are metres with Z upward.",
  },
  {
    section: "Environment",
    title: "See a robot’s reachable workspace",
    target: ".robot-workspace-controls",
    workspace: "environment",
    body: "Turn on Robot workspace to display a cloud of sampled tool positions. Select one robot or All project robots; each uses its saved model, joint limits and base placement. Fit view frames the selected reach. This also appears in Plans → Simulation. It does not move robots or change task assignments. Obstacles, self-collision, other robots and tool orientation can reduce usable reach; compile tasks to validate a motion.",
  },
  {
    section: "Environment",
    title: "Edit objects and destination regions",
    target: ".world-editor",
    workspace: "environment",
    body: "Add objects, destination regions or box obstacles and see them immediately in the viewport. Focus locates each object. Positions, sizes and masses preview locally; Save scene applies the draft to the simulator. Scene changes invalidate existing compiled plans. Updated managed Isaac workers apply box and imported-mesh edits to native USD/PhysX. Fixed workers require a matching prebuilt scene.",
  },
  {
    section: "Environment",
    title: "Record the native simulated scene",
    target: ".scene-recording-panel",
    workspace: "environment",
    body: "Connect the project to an updated NVIDIA Isaac Sim worker, choose video resolution, frame rate, duration and camera position, then Start scene recording. Use native robot controls or run a plan while the camera records; recording itself never moves robots or advances physics. Stop recording finalizes an MP4 and caches it on the RoboDE host for download even after VM shutdown. Reset, disconnect and simulator switches are blocked until recording finishes. Recover worker history retrieves videos after a lost connection. Opening this panel does not boot a VM. Built-in viewport screen recording is separate.",
  },
  {
    section: "Environment",
    title: "Import a 3D object",
    target: ".model-import",
    workspace: "environment",
    body: "In the built-in simulator or an updated managed Isaac worker, Import 3D object accepts GLB, self-contained glTF, OBJ and STL up to 25 MB. Set source up axis, scene role and longest dimension in metres. Imported geometry appears immediately; Save scene retains it. Embedded glTF materials and textures are preserved. Collision checks use the object's declared bounding box. Isaac transfer automatically converts static geometry using neutral materials and the same bounding-box collisions. Textures and animations are not translated.",
  },
  {
    section: "Environment",
    title: "Place robot bases in the environment",
    target: ".placement-editor",
    workspace: "environment",
    body: "Select a robot to show translation arrows. Move (G) drags its position; Rotate (R) shows a yaw rotation ring. Drag the robot itself to move on the ground. Base position & rotation also provides numeric inputs. These are drafts until Use as starting point saves the base and joints together. Revert discards the draft. Changes require recompiling affected plans.",
  },
  {
    section: "Environment",
    title: "Control a joint or end effector",
    target: ".environment-robot-toolbar",
    workspace: "environment",
    body: "Click a robot to open a second interactive 3D model beside the scene. Click its joint labels or tool to select what to control. Adjust a joint slider or tool coordinates: both simulator views update while you move the controls. Joint commands bypass IK; tool positions use the configured solver. Choose a reviewed adapter, including a physical adapter, to exercise its mappings through an isolated simulated transport. Feedback is explicitly simulated. Use as starting point commits the completed preview; Revert discards it and clears pending movement. A managed Isaac worker reloads its native scene on Apply. This tour does not open a control session or move any robot.",
  },
  {
    section: "LLM tasks",
    title: "Select an LLM for each task",
    target: ".step-inspector",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "tasks",
    body: "Each task can select an LLM adapter, or inherit the global default. Draft a refinement sends your instruction through that adapter and returns a validated proposal for you to review and save. Goal generation also has an adapter selector. Robot motion still compiles through the deterministic planner.",
  },
  {
    section: "LLM tasks",
    title: "Run a standalone LLM task",
    target: ".step-inspector",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "tasks",
    body: "Choose LLM task as a task type, then supply its input. No robot assignment is needed. Dependencies can pass earlier LLM answers using {{tasks.task_id.answer}}. During simulation robot trajectories pause while the function runs; Stop cancels the request. Answers appear in execution and immutable run history. Recompile after provider configuration changes.",
  },
  {
    section: "Plans",
    title: "Use direct targets or end-effector poses",
    target: ".step-inspector",
    workspace: "plans",
    planTab: "tasks",
    body: "Task type → Robot command task selects a standardized command. Set actuator uses the exact joint ID and rad/m; Set component uses opening percent. Both bypass IK. Move end effector requires a named tool, explicit frame and XYZ metres, with optional RPY radians, then invokes configured IK. Goal drafting sends the robot’s capabilities, command schema and observed world state with the LLM system rules. Review tasks and compile before simulation; unsupported targets fail explicitly.",
  },
  {
    section: "Plans",
    title: "Name a plan and describe its goal",
    target: ".plan-topline",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "tasks",
    body: "Create a named plan, then describe its goal. Pick and place an apple is a plan; Approach, Grasp, Transfer, Release and Verify are its tasks. Save changes preserves the editable definition.",
  },
  {
    section: "Plans",
    title: "Generate tasks from explicit robot goals",
    target: ".goal-assistant",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "tasks",
    body: "Generate tasks from goals expands supported instructions into atomic tasks. Choose a robot for each goal. Add robot goal supports multi-robot drafting. Independent goals can overlap; goal dependencies become task dependencies.",
  },
  {
    section: "Tasks",
    title: "Edit one atomic task",
    target: ".step-inspector",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "tasks",
    body: "Select a task in the list or graph. Edit its name, task type and explicitly assigned project robot. Move supports saved initial configuration, world coordinates or joint positions. Grasp and Release name an object; placement verification also names a destination region.",
  },
  {
    section: "Tasks",
    title: "Choose parallel work or dependencies",
    target: ".dependency-field",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "tasks",
    body: "Wait for tasks adds explicit prerequisites. The compiler also serializes shared robots, objects and destination regions. Independent tasks on separate robots can run concurrently. Cycles and unknown assignments are rejected.",
  },
  {
    section: "Compilation",
    title: "Compile an immutable revision",
    target: ".plan-topline",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "tasks",
    body: "Compile plan saves current edits and creates a new immutable trajectory, code manifest and configuration snapshot. Review validation before Simulate. Editing tasks, robot configuration or the environment makes old revisions stale.",
  },
  {
    section: "Execution",
    title: "Preview predictions and observe execution",
    target: ".simulation-workspace",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "simulation",
    body: "Simulation shows the cell and predicted trajectory. The timeline scrubs a prediction; Feedback returns to measured or recorded execution state. Scrubbing never commands a robot. Simulate runs a valid current revision, and Stop requests cancellation.",
  },
  {
    section: "Execution",
    title: "Read verification evidence",
    target: ".execution-panel",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "simulation",
    body: "Logs and verification report observed task outcomes, stop requests and confirmed stopped state. Finishing a trajectory alone does not prove success. Automatic plan execution remains simulation-only.",
  },
  {
    section: "Code",
    title: "Inspect generated code",
    target: ".code-view",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "code",
    body: "Generated code shows the exact compiled revision and its task manifest. Export downloads the source. The runtime executes registered validated revisions; it does not evaluate generated plan Python.",
  },
  {
    section: "History",
    title: "Reopen the exact recorded revision",
    target: ".history-view",
    fallback: ".workspace-surface",
    workspace: "plans",
    planTab: "history",
    body: "Run history reopens the exact compiled revision used for execution, with logs, state and verification evidence. Editing or archiving a plan preserves its historical artifacts.",
  },
  {
    section: "Connections",
    title: "Inspect runtime and integration status",
    target: ".connections-modal",
    connections: true,
    body: "This panel shows the runtime, task provider and integration requirements. AI SDK drafting needs a configured provider. Isaac Sim needs a GPU worker and matching USD scene. Native physics and physical hardware require separate acceptance checks.",
  },
  {
    section: "Finish",
    title: "Return to the guide anytime",
    target: '[aria-label="Open tutorial"]',
    body: "Tutorial stays available in the title bar and navigation rail. Use the section menu to jump directly to a control. Closing restores your previous workspace and plan tab.",
    tip: "Start with Robots → Environment → Plans. The project tree always follows Project → Plans → Tasks.",
  },
];

export default function Tutorial({
  onClose,
  onNavigate,
  onStop,
  running,
  layoutKey,
}: {
  onClose: () => void;
  onNavigate: (location: TutorialLocation) => void;
  onStop?: () => void;
  running: boolean;
  layoutKey: string;
}) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);
  const [position, setPosition] = useState({ left: 40, top: 80 });
  const panel = useRef<HTMLDivElement>(null);
  const nextButton = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef(document.activeElement as HTMLElement | null);
  const step = tutorialSteps[index];
  useEffect(() => {
    onNavigate(step);
  }, [index, onNavigate, step]);
  useEffect(() => {
    nextButton.current?.focus();
  }, [index]);
  useEffect(() => () => previousFocus.current?.focus(), []);
  useLayoutEffect(() => {
    let animation = 0,
      attempt = 0;
    let scrolled: Element | null = null;
    const measure = () => {
      const element =
        document.querySelector(step.target) ??
        (step.fallback ? document.querySelector(step.fallback) : null);
      if (!element && attempt++ < 20) {
        animation = requestAnimationFrame(measure);
        return;
      }
      if (element && element !== scrolled) {
        scrolled = element;
        element.scrollIntoView({
          block: "nearest",
          inline: "nearest",
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? "auto"
            : "smooth",
        });
      }
      const raw = element?.getBoundingClientRect();
      const width = Math.min(380, window.innerWidth - 32),
        height = panel.current?.offsetHeight ?? 330;
      if (!raw) {
        setRect(null);
        setPosition({
          left: (window.innerWidth - width) / 2,
          top: Math.max(16, (window.innerHeight - height) / 2),
        });
        return;
      }
      const r = {
        left: Math.max(6, raw.left - 5),
        top: Math.max(6, raw.top - 5),
        width: Math.max(
          0,
          Math.min(raw.right + 5, window.innerWidth - 6) -
            Math.max(6, raw.left - 5),
        ),
        height: Math.max(
          0,
          Math.min(raw.bottom + 5, window.innerHeight - 6) -
            Math.max(6, raw.top - 5),
        ),
      };
      setRect(r);
      let left = r.left + r.width + 18,
        top = r.top;
      if (left + width > window.innerWidth - 16) {
        if (r.left - width - 18 >= 16) left = r.left - width - 18;
        else {
          left = Math.max(
            16,
            Math.min(
              r.left + (r.width - width) / 2,
              window.innerWidth - width - 16,
            ),
          );
          top = r.top + r.height + 18;
          if (top + height > window.innerHeight - 16) top = r.top - height - 18;
        }
      }
      setPosition({
        left: Math.max(16, Math.min(left, window.innerWidth - width - 16)),
        top: Math.max(16, Math.min(top, window.innerHeight - height - 16)),
      });
    };
    measure();
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(animation);
      animation = requestAnimationFrame(measure);
    });
    if (panel.current) observer.observe(panel.current);
    const target = document.querySelector(step.target);
    if (target) observer.observe(target);
    const update = () => {
      cancelAnimationFrame(animation);
      animation = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      cancelAnimationFrame(animation);
      observer.disconnect();
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [step, layoutKey]);
  const next = () =>
    index === tutorialSteps.length - 1 ? onClose() : setIndex((i) => i + 1);
  return (
    <div
      className="tutorial-layer"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        } else if (
          e.key === "ArrowRight" &&
          e.target instanceof HTMLElement &&
          e.target.tagName !== "SELECT"
        ) {
          e.preventDefault();
          next();
        } else if (
          e.key === "ArrowLeft" &&
          e.target instanceof HTMLElement &&
          e.target.tagName !== "SELECT"
        ) {
          e.preventDefault();
          setIndex((i) => Math.max(0, i - 1));
        } else if (e.key === "Tab") {
          const controls = [
            ...panel.current!.querySelectorAll<HTMLElement>(
              "button:not(:disabled),select",
            ),
          ];
          const first = controls[0],
            last = controls.at(-1);
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last?.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }}
    >
      {rect ? (
        <div className="tutorial-spotlight" style={rect} />
      ) : (
        <div className="tutorial-shade" />
      )}
      <div
        className="tutorial-card"
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-title"
        aria-describedby="tutorial-description"
        style={position}
      >
        <div className="tutorial-top">
          <span>
            <BookOpen size={13} />
            GUIDED TUTORIAL
          </span>
          <button aria-label="Close tutorial" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <select
          className="tutorial-jump"
          aria-label="Jump to tutorial section"
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
        >
          {tutorialSteps.map((s, i) => (
            <option key={s.title} value={i}>
              {String(i + 1).padStart(2, "0")} · {s.section} / {s.title}
            </option>
          ))}
        </select>
        <div className="tutorial-copy" key={index}>
          <span className="eyebrow">{step.section.toUpperCase()}</span>
          <h2 id="tutorial-title">{step.title}</h2>
          <p id="tutorial-description">{step.body}</p>
          {step.tip && <div className="tutorial-tip">{step.tip}</div>}
        </div>
        <div
          className="tutorial-progress"
          aria-label={`Tutorial step ${index + 1} of ${tutorialSteps.length}`}
        >
          <div
            style={{ width: `${((index + 1) / tutorialSteps.length) * 100}%` }}
          />
        </div>
        <div className="tutorial-bottom">
          <button
            className="secondary"
            disabled={index === 0}
            onClick={() => setIndex((i) => i - 1)}
          >
            <ArrowLeft size={13} />
            Back
          </button>
          <span>
            {index + 1} / {tutorialSteps.length}
          </span>
          <button ref={nextButton} className="primary" onClick={next}>
            {index === tutorialSteps.length - 1 ? (
              <>
                <Check size={13} />
                Finish
              </>
            ) : (
              <>
                Next
                <ArrowRight size={13} />
              </>
            )}
          </button>
        </div>
        {running && (
          <div className="tutorial-running">
            <span>Simulation continues while this guide is open.</span>
            <button onClick={onStop}>
              <Square size={11} />
              Stop simulation
            </button>
          </div>
        )}
        <div className="tutorial-keyboard">
          ← → Navigate <span>Esc Close</span>
        </div>
      </div>
    </div>
  );
}

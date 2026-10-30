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
    "section": "Orientation",
    "title": "Welcome to RoboDE",
    "target": ".titlebar",
    "body": "One project contains multiple plans. Each plan contains tasks with explicit robot assignments and actuator commands. The Planner LLM creates tasks; the Task LLM produces commands. You review the result before running.",
    "tip": "Use arrow keys or Next. Escape closes the tour. Tutorial opens it anytime."
  },
  {
    "section": "Projects",
    "title": "Choose your project",
    "target": "[aria-label=\"Select project\"]",
    "body": "Choose a project or create one with the plus button. Each project keeps its robot instances, environment, plans and execution history."
  },
  {
    "section": "Setup",
    "title": "Add a reusable robot",
    "target": "[aria-label=\"Open configuration\"]",
    "configuration": "robots",
    "fallback": ".configuration-modal",
    "body": "In Robot library choose Add robot · guided setup. Follow Robot → Controls → Mapping → Test → Save. Select a model or import a URDF with its meshes. Choose Physical hardware or a Virtual simulator target."
  },
  {
    "section": "Setup",
    "title": "Map and test your controls",
    "target": ".global-robot-library",
    "configuration": "robots",
    "fallback": ".configuration-modal",
    "body": "Choose an existing control adapter or generate actuator functions from vendor documentation. Virtual robots can create a simulator adapter directly. Review joint mappings and the tool, test actuators and MOVE, then save. Advanced units and coupling remain in Expert mode."
  },
  {
    "section": "AI models",
    "title": "Choose the Planner LLM and Task LLM",
    "target": ".planner-converter-settings",
    "configuration": "llm",
    "fallback": ".configuration-modal",
    "body": "Add an Ollama or OpenAI-compatible connection. Find its models, save and test it. Choose the workspace Planner LLM and Task LLM here; they can be different models. Each plan can also choose its own. Nemotron is available through a provider offering it. Robot setup uses the Task LLM. System instructions are supplied internally."
  },
  {
    "section": "Robots",
    "title": "Add robots to the project",
    "target": ".robot-editor",
    "workspace": "robots",
    "fallback": ".workspace-surface",
    "body": "Select a global robot and a compatible control adapter, then add or save the project instance. Physical and Virtual targets are separate. Selecting an instance here never reassigns tasks."
  },
  {
    "section": "Environment",
    "title": "Set up the workspace",
    "target": ".environment-workspace",
    "workspace": "environment",
    "fallback": ".workspace-surface",
    "body": "Add named objects, obstacles and target regions. Import supported 3D assets and save scene changes. Select a robot to open its joint and tool controls. Move or rotate the robot with the handles; save it as the starting point or revert."
  },
  {
    "section": "Controls",
    "title": "Test joints and tools",
    "target": ".environment-robot-toolbar",
    "workspace": "environment",
    "fallback": ".workspace-surface",
    "body": "Use Robot controls to select a robot and open the 3D control panel. Joint and end-effector movement updates the connected simulator. Simulated transport is the default. Physical connection requires the warning acknowledgement and separate arming."
  },
  {
    "section": "Isaac Sim",
    "title": "Live connection and recorded playback",
    "target": ".environment-workspace",
    "workspace": "environment",
    "fallback": ".workspace-surface",
    "body": "NVIDIA Isaac Sim keeps its existing live connection and recorded playback modes. Environment owns simulator selection and scene synchronization. Native scene recording captures the Isaac camera, and saved recordings remain available for playback. Opening the panel does not boot a cloud VM."
  },
  {
    "section": "Plans",
    "title": "Project → Plans → Tasks",
    "target": ".project-tree",
    "workspace": "plans",
    "fallback": ".workspace-surface",
    "body": "Create multiple named plans under one project. Expand a plan to see its tasks. Selecting a task opens its assigned robot, instruction, commands and dependencies."
  },
  {
    "section": "Plans",
    "title": "Generate a complete plan",
    "target": ".plan-composer",
    "workspace": "plans",
    "planTab": "tasks",
    "fallback": ".workspace-surface",
    "body": "Enter the high-level instruction. Auto assign lets the Planner LLM choose project robots; Use selected robots limits its choices. Name a robot in the instruction for an explicit assignment. Generate plan runs the Planner LLM, then the Task LLM automatically. Clarification questions pause generation."
  },
  {
    "section": "Tasks",
    "title": "Edit tasks and actuator commands",
    "target": ".task-authoring",
    "workspace": "plans",
    "planTab": "tasks",
    "fallback": ".workspace-surface",
    "body": "Select a task to edit its instruction or assigned robot, inspect converted calls, or add commands from that robot’s catalog. Add task creates another editable task. Changing intent or robot clears outdated calls. Regenerate replaces edits only after you explicitly allow it."
  },
  {
    "section": "Tasks",
    "title": "Dependencies and concurrent robots",
    "target": ".task-dependencies",
    "workspace": "plans",
    "planTab": "tasks",
    "fallback": ".task-authoring",
    "body": "Choose which tasks must finish first. Independent robots can move concurrently. Tasks sharing robots or scene resources serialize. Remove or repair dependent links before deleting a prerequisite."
  },
  {
    "section": "Validation",
    "title": "Validate before running",
    "target": ".composer-actions",
    "workspace": "plans",
    "planTab": "tasks",
    "fallback": ".workspace-surface",
    "body": "Validate plan checks unresolved commands, compiles deterministic motion and checks limits, workspace and collisions. Findings appear with the plan. Incomplete checking blocks physical execution. Run simulation uses the exact validated revision; edits make old validation stale."
  },
  {
    "section": "Execution",
    "title": "Preview, run and stop",
    "target": ".simulation-workspace",
    "workspace": "plans",
    "planTab": "simulation",
    "fallback": ".workspace-surface",
    "body": "The simulation view shows motion feedback and a preview timeline. Execution and verification show task outcomes. Stop requests and confirmed stopped feedback are reported separately. Expert mode contains reviewed and armed physical execution."
  },
  {
    "section": "History",
    "title": "Preserved plan revisions and runs",
    "target": ".history-view",
    "workspace": "plans",
    "planTab": "history",
    "fallback": ".workspace-surface",
    "body": "Run history opens the exact immutable revision used for that run. Editing or archiving a plan preserves its previous artifacts and results."
  },
  {
    "section": "Finish",
    "title": "Return anytime",
    "target": "[aria-label=\"Open tutorial\"]",
    "body": "Start with robot setup and your environment, then give the project a plan. The normal flow is Generate plan → Edit tasks → Validate plan → Run simulation. Expert mode keeps diagnostics and advanced controls available."
  }
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

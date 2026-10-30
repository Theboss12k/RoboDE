import Feedback from "./ui/Feedback";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api } from "./api";
import type { LLMConfiguration, ProjectDetail } from "./types";
import GlobalRobotLibrary from "./GlobalRobotLibrary";
import RobotSetup from "./RobotSetup";
import WorkspaceAccess from "./WorkspaceAccess";
import AIModels from "./AIModels";
import ControlAdapters from "./ControlAdapters";
import { ModeSwitch } from "./mode";

type Section = "robots" | "adapters" | "ai" | "access";
const sections: Record<Section, string> = { robots: "Robot library", adapters: "Control adapters", ai: "AI Models", access: "Workspace" };

export default function Configuration({
  initialTab = "robots",
  disabled,
  onClose,
  onChanged,
}: {
  /** "llm" is accepted for tutorial links saved before the AI Models section existed. */
  initialTab?: Section | "llm";
  detail: ProjectDetail | null;
  disabled: boolean;
  onClose: () => void;
  onChanged: () => void;
  onAdded: () => void;
}) {
  const normalized = (t: Section | "llm"): Section => (t === "llm" ? "ai" : t);
  const [tab, setTab] = useState<Section>(normalized(initialTab));
  const [providers, setProviders] = useState<LLMConfiguration>({ adapters: [], default_id: null });
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [changes, setChanges] = useState(0);
  useEffect(() => setTab(normalized(initialTab)), [initialTab]);
  const load = async () => setProviders(await api<LLMConfiguration>("/llm/adapters"));
  useEffect(() => { void load().catch((e) => setError(e.message)); }, []);
  const changed = () => { setChanges((n) => n + 1); onChanged(); };
  const locked = busy || disabled;
  return (
    <div className="modal configuration-modal" role="dialog" aria-modal="true" aria-label="Global configuration">
      <div className="section-toolbar">
        <div>
          <span className="eyebrow">GLOBAL CONFIGURATION</span>
          <h2>Robots, adapters & AI models</h2>
        </div>
        <button aria-label="Close configuration" disabled={busy} onClick={onClose}><X size={17} /></button>
        {/* The header switch sits behind this dialog, so the dialog repeats it; it follows Close so Close keeps initial focus. */}
        <ModeSwitch />
      </div>
      <nav className="view-tabs" aria-label="Configuration sections">
        {(Object.keys(sections) as Section[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} disabled={busy} onClick={() => setTab(t)}>{sections[t]}</button>
        ))}
      </nav>
      <Feedback message={error} />
      {/* Sections stay mounted while hidden so unsaved setup edits survive tab and mode changes. */}
      <div hidden={tab !== "robots"}>
        <RobotSetup disabled={locked} onChanged={changed} onBusyChange={setBusy} providers={providers} />
        <details className="expert-only"><summary>Legacy robot definitions & adapters</summary><GlobalRobotLibrary disabled={locked} onChanged={changed} onBusyChange={setBusy} /></details>
      </div>
      {tab === "adapters" && <ControlAdapters refreshKey={changes} />}
      {tab === "ai" && <AIModels providers={providers} disabled={locked} onSaved={async () => { await load(); changed(); }} />}
      {tab === "access" && <WorkspaceAccess />}
    </div>
  );
}

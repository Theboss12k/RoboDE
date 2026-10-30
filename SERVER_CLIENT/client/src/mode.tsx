import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

/** Simple shows names, readiness and warnings; Expert adds IDs, hashes, code and advanced settings.
 *  Expert-only markup stays mounted and is hidden with CSS, so switching keeps selections and unsaved edits. */
export type Mode = "simple" | "expert";
const KEY = "robode.interface-mode";
const ModeContext = createContext<{ mode: Mode; setMode: (mode: Mode) => void }>({ mode: "simple", setMode: () => {} });

function stored(): Mode {
  try {
    return localStorage.getItem(KEY) === "expert" ? "expert" : "simple";
  } catch {
    return "simple";
  }
}

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(stored);
  useEffect(() => {
    document.documentElement.dataset.mode = mode;
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      // Private windows may block storage; the choice still applies to this session.
    }
  }, [mode]);
  return <ModeContext.Provider value={{ mode, setMode }}>{children}</ModeContext.Provider>;
}

export const useMode = () => {
  const { mode, setMode } = useContext(ModeContext);
  return { mode, setMode, expert: mode === "expert" };
};

export function ModeSwitch() {
  const { mode, setMode } = useMode();
  return (
    <div className="mode-switch" role="radiogroup" aria-label="Interface mode">
      {(["simple", "expert"] as const).map((m) => (
        <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}
          title={m === "simple" ? "Names, readiness and warnings" : "Adds IDs, hashes, code and advanced settings"}>
          {m === "simple" ? "Simple" : "Expert"}
        </button>
      ))}
    </div>
  );
}

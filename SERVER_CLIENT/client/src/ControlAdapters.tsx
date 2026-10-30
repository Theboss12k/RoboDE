import { useEffect, useState } from "react";
import { api } from "./api";
import Feedback from "./ui/Feedback";

export type Driver = {
  id: string; hash: string; version?: number; status?: string; source_code: string; reviewed_hash: string | null;
  test_report: { passed: boolean } | null; provenance?: { model?: string | null } | null;
  definition: { name: string; category: "virtual" | "physical"; sdk_version: string;
    functions: { id: string; vendor_method?: string; mode: string; unit: string; minimum: number; maximum: number; documentation_quote?: string }[]; [key: string]: unknown };
};

export const driverReadiness = (d: Driver) => [
  { label: d.reviewed_hash === d.hash ? "Reviewed" : "Review required", state: d.reviewed_hash === d.hash ? "ok" : "todo" },
  { label: d.test_report?.passed ? "Simulated tests passed" : d.test_report ? "Simulated tests failed" : "Tests required", state: d.test_report?.passed ? "ok" : d.test_report ? "bad" : "todo" },
];

/** Reusable robot drivers. "Control adapter" always means a robot driver, never an AI model. */
export default function ControlAdapters({ refreshKey }: { refreshKey?: unknown }) {
  const [drivers, setDrivers] = useState<Driver[]>([]), [error, setError] = useState("");
  useEffect(() => { void api<Driver[]>("/library/drivers").then(setDrivers).catch((e) => setError(e.message)); }, [refreshKey]);
  return (
    <section className="config-card" aria-label="Control adapters">
      <h3>Control adapters</h3>
      <p>Reusable robot drivers. Each function moves one actuator. Create adapters during robot setup; projects pair a saved robot with a compatible adapter.</p>
      <Feedback message={error} />
      <div className="library-models">
        {drivers.map((d) => (
          <article className="config-card" key={d.id}>
            <span className={`tiny-tag ${d.definition.category === "physical" ? "danger" : ""}`}>{d.definition.category === "physical" ? "Physical · robot hardware" : "Virtual · simulator"}</span>
            <h4>{d.definition.name}</h4>
            <small>{d.definition.functions.length} actuator functions{d.provenance?.model ? ` · generated with ${d.provenance.model}` : ""}</small>
            <ul className="readiness">{driverReadiness(d).map((r) => <li key={r.label} className={r.state}>{r.label}</li>)}</ul>
            {d.definition.category === "physical" && <small>Connecting hardware requires the red connection warning, device validation and separate arming in a project.</small>}
            <small className="expert-only">ID {d.id} · v{d.version ?? 1} · hash {d.hash.slice(0, 12)} · SDK {d.definition.sdk_version}</small>
          </article>
        ))}
      </div>
      {!drivers.length && <p>No control adapters yet. Add a robot in Robot library to create one.</p>}
    </section>
  );
}

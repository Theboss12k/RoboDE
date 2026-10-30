import { useState } from "react";
import { post } from "./api";
import type { Driver } from "./ControlAdapters";
import Feedback from "./ui/Feedback";

export type Issue = { field: string; message: string };
type Row = { id?: string; vendor_method?: string; argument?: string; mode?: string; unit?: string; minimum?: number; maximum?: number;
  documentation_quote?: string; write_style?: string; vendor_joint?: string; valid?: boolean };
export type GeneratedDraft = { name: string; category: "virtual" | "physical"; sdk_version: string; documentation: string; functions: Row[];
  sdk_module: string; client_factory: string; feedback_method: string; stop_method: string; disconnect_method: string; watchdog_method: string };
const units = ["rad", "deg", "m", "mm", "rad/s", "deg/s", "m/s", "mm/s"];

/** Review an AI-generated adapter as a function table instead of raw JSON. Valid rows are kept;
 *  missing physical SDK details stay empty until the user supplies them. */
export default function GeneratedFunctions({ draft: initial, issues, disabled, onSaved }: { draft: GeneratedDraft; issues: Issue[]; disabled: boolean; onSaved: (d: Driver) => void }) {
  const [draft, setDraft] = useState(initial), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const rowIssues = (i: number) => issues.filter((x) => x.field.startsWith(`functions[${i}]`));
  const general = issues.filter((x) => !x.field.startsWith("functions["));
  const setRow = (i: number, patch: Row) => setDraft({ ...draft, functions: draft.functions.map((r, n) => (n === i ? { ...r, ...patch, valid: undefined } : r)) });
  const physical = draft.category === "physical";
  const missing = physical ? (["sdk_module", "client_factory"] as const).filter((k) => !draft[k].trim()) : [];
  const sentences = draft.documentation.split(/(?<=\.)\s+|\n/).map((s) => s.trim()).filter(Boolean);
  return (
    <section className="config-card" aria-label="Generated adapter functions">
      <h4>Review generated functions</h4>
      <p>The AI model's answer needs more information. Valid functions are kept; correct the highlighted rows, then save the adapter.</p>
      {general.map((x) => <p key={x.field + x.message} className="field-issue" role="note">{x.field.replaceAll("_", " ")}: {x.message}</p>)}
      <table className="mapping-table function-table">
        <thead><tr><th>Function</th><th>Actuator / SDK method</th><th>Units</th><th>Limits</th><th>Documentation reference</th><th /></tr></thead>
        <tbody>{draft.functions.map((r, i) => (
          <tr key={i} className={r.valid === false || rowIssues(i).length ? "invalid" : ""}>
            <td><input aria-label={`Function ${i + 1} name`} value={r.id ?? ""} disabled={disabled} onChange={(e) => setRow(i, { id: e.target.value })} />
              {rowIssues(i).map((x) => <p key={x.field + x.message} className="field-issue">{x.field.replace(`functions[${i}]`, "").replace(/^\./, "") || "function"}: {x.message}</p>)}</td>
            <td><input aria-label={`Function ${i + 1} SDK method`} value={r.vendor_method ?? ""} disabled={disabled} onChange={(e) => setRow(i, { vendor_method: e.target.value })} /></td>
            <td><select aria-label={`Function ${i + 1} units`} value={r.unit ?? ""} disabled={disabled} onChange={(e) => setRow(i, { unit: e.target.value, mode: e.target.value.endsWith("/s") ? "velocity" : "position" })}>
              <option value="">Choose</option>{units.map((u) => <option key={u}>{u}</option>)}</select></td>
            <td><div className="configuration-grid">
              <input aria-label={`Function ${i + 1} minimum`} type="number" step="any" value={r.minimum ?? ""} disabled={disabled} onChange={(e) => setRow(i, { minimum: e.target.value === "" ? undefined : Number(e.target.value) })} />
              <input aria-label={`Function ${i + 1} maximum`} type="number" step="any" value={r.maximum ?? ""} disabled={disabled} onChange={(e) => setRow(i, { maximum: e.target.value === "" ? undefined : Number(e.target.value) })} /></div></td>
            <td><select aria-label={`Function ${i + 1} documentation reference`} value={r.documentation_quote ?? ""} disabled={disabled} onChange={(e) => setRow(i, { documentation_quote: e.target.value })}>
              <option value="">Choose the sentence that documents it</option>{sentences.map((s) => <option key={s} value={s}>{s.slice(0, 120)}</option>)}</select></td>
            <td><button aria-label={`Remove function ${i + 1}`} disabled={disabled} onClick={() => setDraft({ ...draft, functions: draft.functions.filter((_, n) => n !== i) })}>Remove</button></td>
          </tr>))}</tbody>
      </table>
      <button disabled={disabled} onClick={() => setDraft({ ...draft, functions: [...draft.functions, { mode: "position", unit: "rad", argument: "value", write_style: "single" }] })}>Add function</button>
      <div className="configuration-grid">
        {(["stop_method", "feedback_method", "disconnect_method"] as const).map((k) => <label className="field" key={k}>{k.replace("_method", "").replace(/^./, (c) => c.toUpperCase())} method · optional, must be documented
          <input value={draft[k]} disabled={disabled} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} /></label>)}
        {physical && (["sdk_module", "client_factory"] as const).map((k) => <label className="field" key={k}>{k === "sdk_module" ? "Vendor SDK module (required)" : "SDK client factory (required)"}
          <input aria-label={k === "sdk_module" ? "Vendor SDK module" : "SDK client factory"} value={draft[k]} disabled={disabled} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} /></label>)}
      </div>
      {!!missing.length && <p className="field-issue" role="note">Supply the {missing.map((k) => k.replace("_", " ")).join(" and ")} from the vendor SDK documentation. RoboDE never guesses hardware integration details.</p>}
      <Feedback message={error} />
      <button className="primary" disabled={disabled || busy || !!missing.length || !draft.functions.length} onClick={async () => {
        setBusy(true); setError("");
        try {
          const functions = draft.functions.map(({ valid: _valid, ...r }) => ({ argument: "value", write_style: "single", vendor_joint: "", ...r }));
          onSaved(await post<Driver>("/library/drivers", { ...draft, functions, source_code: "", client_factory: draft.client_factory || "Client" }));
        } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
      }}>Save adapter from table</button>
    </section>
  );
}

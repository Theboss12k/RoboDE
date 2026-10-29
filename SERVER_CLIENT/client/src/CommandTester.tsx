import { useEffect, useState } from "react";
import { Play } from "lucide-react";
import type { AdapterBundle, ControlSession } from "./types";
export default function CommandTester({
  adapter,
  session,
  busy,
  onRun,
}: {
  adapter: AdapterBundle;
  session: ControlSession | null;
  busy: boolean;
  onRun: (id: string, args: Record<string, number>) => void;
}) {
  const commands = adapter.commands ?? [];
  const [selected, setSelected] = useState(commands[0]?.id ?? "");
  const command = commands.find((c) => c.id === selected);
  const [args, setArgs] = useState<Record<string, number>>({});
  useEffect(
    () =>
      setArgs(
        Object.fromEntries(
          Object.entries(command?.parameters ?? {}).map(([key, p]) => [
            key,
            p.default,
          ]),
        ),
      ),
    [command],
  );
  const [results, setResults] = useState<Record<string, string>>(
    Object.fromEntries(
      (adapter.command_tests ?? []).map((r) => [r.command_id, r.status]),
    ),
  );
  useEffect(() => {
    const r = session?.command_run;
    if (r?.finished_at)
      setResults((old) => ({ ...old, [r.command_id]: r.status }));
  }, [session?.command_run?.id, session?.command_run?.finished_at]);
  const running = session?.command_run?.status === "running";
  return (
    <section className="command-tester">
      <div className="section-toolbar">
        <h3>Test available commands</h3>
        <span className="tiny-tag">Built-in simulator</span>
      </div>
      <div className="command-test-layout">
        <div className="command-catalog">
          {commands.map((c) => (
            <button
              key={c.id}
              className={c.id === selected ? "selected" : ""}
              disabled={busy || running}
              onClick={() => setSelected(c.id)}
            >
              <strong>{c.name}</strong>
              <small>
                {c.id}
                {!c.simulation_supported
                  ? " · unavailable"
                  : results[c.id]
                    ? ` · ${results[c.id]}`
                    : ""}
              </small>
            </button>
          ))}
        </div>
        <div>
          {command && (
            <>
              <h3>{command.name}</h3>
              <p>{command.description}</p>
              {command.vendor_command && (
                <code className="vendor-binding">{command.vendor_command}</code>
              )}
              {!command.simulation_supported ? (
                <p className="inline-note">{command.unsupported_reason}</p>
              ) : (
                <>
                  <div className="command-test-parameters">
                    {Object.entries(command.parameters).map(([key, p]) => (
                      <label className="field" key={key}>
                        {key} · {p.unit}
                        <input
                          aria-label={`Test parameter ${key}`}
                          type="number"
                          step="any"
                          min={p.min}
                          max={p.max}
                          value={args[key] ?? p.default}
                          disabled={busy || running}
                          onChange={(e) =>
                            setArgs({ ...args, [key]: Number(e.target.value) })
                          }
                        />
                        <small>
                          {p.min}…{p.max} {p.unit}
                        </small>
                      </label>
                    ))}
                  </div>
                  <button
                    className="primary"
                    aria-label={`Test ${command.name}`}
                    disabled={
                      !session ||
                      session.mode !== "test" ||
                      busy ||
                      running ||
                      adapter.reviewed_hash !== adapter.hash ||
                      !adapter.test_report?.passed
                    }
                    onClick={() => onRun(command.id, args)}
                  >
                    <Play size={13} />
                    {running ? "Command running…" : `Test ${command.name}`}
                  </button>
                </>
              )}
              <details>
                <summary>Command recipe · {command.steps.length} steps</summary>
                <pre>{JSON.stringify(command.steps, null, 2)}</pre>
              </details>
            </>
          )}
          {session && session.mode !== "test" && (
            <p className="inline-note">
              Choose Simulated adapter test to exercise named commands.
            </p>
          )}
          {session?.command_run && (
            <div
              className={`command-result ${session.command_run.status}`}
              role="status"
            >
              <strong>
                {session.command_run.command_id} · {session.command_run.status}
              </strong>
              <progress max="1" value={session.command_run.progress} />
              <small>
                Step {session.command_run.current_step} ·{" "}
                {session.command_run.scope.replaceAll("_", " ")} · stopped{" "}
                {session.command_run.stopped_verified ? "confirmed" : "pending"}
              </small>
              {session.command_run.error && <p>{session.command_run.error}</p>}
              <details>
                <summary>Simulated translation and feedback trace</summary>
                <pre>{JSON.stringify(session.command_run.trace, null, 2)}</pre>
              </details>
            </div>
          )}
          <p className="command-test-note">
            These tests exercise the adapter’s joint translation through an
            injected simulated transport. Vendor source remains a draft. Native
            Isaac physics and physical hardware require separate validation.
          </p>
        </div>
      </div>
    </section>
  );
}

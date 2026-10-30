import type { AdapterBundle } from "./types";
export type Target = "physical" | "virtual";
export default function RobotAdapterPicker({
  target,
  onTarget,
  value,
  onChange,
  adapters,
  disabled = false,
}: {
  target: Target;
  onTarget: (t: Target) => void;
  value: string;
  onChange: (a: string) => void;
  adapters: AdapterBundle[];
  disabled?: boolean;
}) {
  return (
    <>
      <div
        className="target-choice"
        role="group"
        aria-label="Project robot target"
      >
        <button
          type="button"
          disabled={disabled}
          aria-pressed={target === "virtual"}
          onClick={() => onTarget("virtual")}
        >
          Virtual · simulator
        </button>
        <button
          type="button"
          disabled={disabled}
          aria-pressed={target === "physical"}
          onClick={() => onTarget("physical")}
        >
          Physical · hardware
        </button>
      </div>
      <label className="field">
        Global control adapter
        <select
          aria-label="Project robot adapter"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Select compatible adapter</option>
          {target === "virtual" && (
            <>
              <option value="mock">Built-in simulator · virtual</option>
              <option value="isaac_sim">NVIDIA Isaac Sim · virtual</option>
            </>
          )}
          {adapters
            .filter(
              (a) =>
                a.category === target &&
                a.reviewed_hash === a.hash &&
                a.test_report?.passed,
            )
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.category}
              </option>
            ))}
        </select>
      </label>
      <p>
        {target === "physical"
          ? "Testing is simulated by default. Target selection does not arm hardware. Physical execution requires a published mapping, complete checking, device qualification and explicit arming of the exact revision."
          : "This adapter is saved on the instance. Select the simulation engine and connection separately in Environment."}
      </p>
    </>
  );
}

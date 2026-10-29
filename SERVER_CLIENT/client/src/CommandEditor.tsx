import wavePlan from "../../server/examples/plans/wave.json";
import { Plus, Trash2 } from "lucide-react";
import type { AdapterCommand, CellRobot } from "./types";
export function waveExample(): AdapterCommand {
  return {
    id: "wave",
    name: "Wave",
    description:
      "Turn right, left and return to centre. Other joints stay unchanged.",
    vendor_command: "",
    parameters: {},
    simulation_supported: true,
    unsupported_reason: "",
    steps: [
      ...wavePlan.tasks.flatMap((task) => {
        if (!task.command || task.command.type !== "SET_ACTUATOR") return [];
        // The adapter test worker consumes bounded joint recipes internally.
        // The reusable example itself is a PlanDefinition with StandardCommands.
        return [{operation:"move" as const,values:{[task.command.target]:task.command.value},duration:0.6}];
      }),
      { operation: "feedback", values: {}, duration: 0.5 },
    ],
  };
}
export default function CommandEditor({
  commands,
  robot,
  onChange,
  disabled = false,
}: {
  commands: AdapterCommand[];
  robot: CellRobot;
  onChange: (commands: AdapterCommand[]) => void;
  disabled?: boolean;
}) {
  const joints = robot.model.actuators.actuators;
  const update = (index: number, patch: Partial<AdapterCommand>) =>
    onChange(commands.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  return (
    <section className="command-editor">
      <div className="section-toolbar">
        <h3>Command definitions</h3>
        <button
          type="button"
          className="secondary"
          disabled={disabled || commands.length >= 32}
          onClick={() =>
            onChange([
              ...commands,
              {
                id: `custom_${commands.length + 1}`,
                name: "Custom task",
                description: "",
                vendor_command: "",
                parameters: {},
                steps: [{ operation: "feedback", values: {}, duration: 0.5 }],
                simulation_supported: true,
                unsupported_reason: "",
              },
            ])
          }
        >
          <Plus size={13} /> Add custom command
        </button>
      </div>
      <p>
        Define tasks as simulator steps. Joint values use model units; enter a
        number or a parameter reference such as <code>$angle</code>. Standard
        joint, gripper, feedback and stop commands are included automatically.
      </p>
      {commands.map((c, i) => (
        <details
          className="command-definition"
          key={i}
          open={commands.length === 1 || undefined}
        >
          <summary>
            {c.name || c.id} · {c.steps.length} steps
            {!c.simulation_supported ? " · unavailable" : ""}
          </summary>
          <div className="command-definition-body">
            <div className="configuration-grid">
              <label className="field">
                Command ID
                <input
                  aria-label={`Command ${i + 1} ID`}
                  value={c.id}
                  disabled={disabled}
                  onChange={(e) => update(i, { id: e.target.value })}
                />
              </label>
              <label className="field">
                Display name
                <input
                  aria-label={`Command ${i + 1} name`}
                  value={c.name}
                  disabled={disabled}
                  onChange={(e) => update(i, { name: e.target.value })}
                />
              </label>
            </div>
            <label className="field">
              Description
              <input
                aria-label={`Command ${i + 1} description`}
                value={c.description}
                disabled={disabled}
                onChange={(e) => update(i, { description: e.target.value })}
              />
            </label>
            <label className="field">
              Vendor function / signature · optional
              <input
                aria-label={`Command ${i + 1} vendor binding`}
                value={c.vendor_command}
                disabled={disabled}
                onChange={(e) => update(i, { vendor_command: e.target.value })}
              />
            </label>
            <label className="review-check">
              <input
                type="checkbox"
                checked={c.simulation_supported}
                disabled={disabled}
                onChange={(e) =>
                  update(i, {
                    simulation_supported: e.target.checked,
                    unsupported_reason: e.target.checked
                      ? ""
                      : "No simulator recipe has been defined.",
                    steps: e.target.checked
                      ? [{ operation: "feedback", values: {}, duration: 0.5 }]
                      : [],
                  })
                }
              />
              Simulator implementation defined
            </label>
            {!c.simulation_supported ? (
              <p className="inline-note">{c.unsupported_reason}</p>
            ) : (
              <>
                <div className="section-toolbar">
                  <h4>Numeric parameters</h4>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      let n = 1;
                      while (c.parameters[`value_${n}`]) n++;
                      update(i, {
                        parameters: {
                          ...c.parameters,
                          [`value_${n}`]: {
                            min: -0.5,
                            max: 0.5,
                            default: 0,
                            unit: "rad",
                            description: "",
                          },
                        },
                      });
                    }}
                  >
                    Add parameter
                  </button>
                </div>
                {Object.entries(c.parameters).map(([key, p], n) => (
                  <div className="command-parameter" key={n}>
                    <label>
                      Name
                      <input
                        aria-label={`Command ${i + 1} parameter ${n + 1} name`}
                        value={key}
                        disabled={disabled}
                        onChange={(e) => {
                          const entries = Object.entries(c.parameters);
                          entries[n] = [e.target.value, p];
                          update(i, {
                            parameters: Object.fromEntries(entries),
                          });
                        }}
                      />
                    </label>
                    {(["min", "max", "default"] as const).map((field) => (
                      <label key={field}>
                        {field}
                        <input
                          aria-label={`Command ${i + 1} parameter ${n + 1} ${field}`}
                          type="number"
                          step="any"
                          value={p[field]}
                          disabled={disabled}
                          onChange={(e) =>
                            update(i, {
                              parameters: {
                                ...c.parameters,
                                [key]: {
                                  ...p,
                                  [field]: Number(e.target.value),
                                },
                              },
                            })
                          }
                        />
                      </label>
                    ))}
                    <label>
                      Unit
                      <select
                        aria-label={`Command ${i + 1} parameter ${n + 1} unit`}
                        value={p.unit}
                        disabled={disabled}
                        onChange={(e) =>
                          update(i, {
                            parameters: {
                              ...c.parameters,
                              [key]: { ...p, unit: e.target.value },
                            },
                          })
                        }
                      >
                        <option value="">None</option>
                        <option>rad</option>
                        <option>m</option>
                      </select>
                    </label>
                    <button
                      type="button"
                      aria-label={`Remove parameter ${n + 1} from command ${i + 1}`}
                      disabled={disabled}
                      onClick={() =>
                        update(i, {
                          parameters: Object.fromEntries(
                            Object.entries(c.parameters).filter(
                              ([k]) => k !== key,
                            ),
                          ),
                        })
                      }
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
                <h4>Simulator recipe</h4>
                {c.steps.map((step, j) => (
                  <div className="command-step" key={j}>
                    <div className="section-toolbar">
                      <label>
                        Step {j + 1}
                        <select
                          aria-label={`Command ${i + 1} step ${j + 1} operation`}
                          value={step.operation}
                          disabled={disabled}
                          onChange={(e) => {
                            const operation = e.target
                              .value as typeof step.operation;
                            const motion = [
                              "move",
                              "increment",
                              "gripper",
                            ].includes(operation);
                            update(i, {
                              steps: c.steps.map((s, k) =>
                                k === j
                                  ? {
                                      operation,
                                      duration: 0.5,
                                      values:
                                        operation === "gripper"
                                          ? {
                                              gripper:
                                                joints.gripper?.max ?? 0.08,
                                            }
                                          : motion
                                            ? {
                                                [Object.keys(joints)[0]]:
                                                  operation === "increment"
                                                    ? 0
                                                    : robot.instance
                                                        .initial_configuration
                                                        .actuator_positions[
                                                        Object.keys(joints)[0]
                                                      ],
                                              }
                                            : {},
                                    }
                                  : s,
                              ),
                            });
                          }}
                        >
                          {[
                            "move",
                            "increment",
                            ...(joints.gripper ? ["gripper"] : []),
                            "wait",
                            "feedback",
                            "stop",
                          ].map((op) => (
                            <option key={op} value={op}>
                              {
                                {
                                  move: "Move joints",
                                  increment: "Increment joints",
                                  gripper: "Set gripper",
                                  wait: "Wait",
                                  feedback: "Read feedback",
                                  stop: "Stop",
                                }[op]
                              }
                            </option>
                          ))}
                        </select>
                      </label>
                      {!["feedback", "stop"].includes(step.operation) && (
                        <label>
                          {step.operation === "wait"
                            ? "Wait · s"
                            : "Minimum duration · s"}
                          <input
                            aria-label={`Command ${i + 1} step ${j + 1} duration`}
                            type="number"
                            min=".05"
                            max="10"
                            step=".1"
                            value={step.duration}
                            disabled={disabled}
                            onChange={(e) =>
                              update(i, {
                                steps: c.steps.map((s, k) =>
                                  k === j
                                    ? { ...s, duration: Number(e.target.value) }
                                    : s,
                                ),
                              })
                            }
                          />
                        </label>
                      )}
                      <button
                        type="button"
                        aria-label={`Remove step ${j + 1} from command ${i + 1}`}
                        disabled={disabled}
                        onClick={() =>
                          update(i, {
                            steps: c.steps.filter((_, k) => k !== j),
                          })
                        }
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                    {Object.entries(step.values).map(([key, value], n) => (
                      <div className="command-joint" key={n}>
                        <select
                          aria-label={`Command ${i + 1} step ${j + 1} joint ${n + 1}`}
                          value={key}
                          disabled={disabled || step.operation === "gripper"}
                          onChange={(e) => {
                            const entries = Object.entries(step.values);
                            entries[n] = [e.target.value, value];
                            update(i, {
                              steps: c.steps.map((s, k) =>
                                k === j
                                  ? {
                                      ...s,
                                      values: Object.fromEntries(entries),
                                    }
                                  : s,
                              ),
                            });
                          }}
                        >
                          {Object.entries(joints).map(([joint, a]) => (
                            <option key={joint} value={joint}>
                              {joint} · {a.unit} · {a.min}…{a.max}
                            </option>
                          ))}
                        </select>
                        <input
                          aria-label={`Command ${i + 1} step ${j + 1} value ${n + 1}`}
                          value={value}
                          disabled={disabled}
                          placeholder="Number or $parameter"
                          onChange={(e) => {
                            const raw = e.target.value;
                            update(i, {
                              steps: c.steps.map((s, k) =>
                                k === j
                                  ? {
                                      ...s,
                                      values: {
                                        ...s.values,
                                        [key]:
                                          raw.trim() !== "" &&
                                          Number.isFinite(Number(raw))
                                            ? Number(raw)
                                            : raw,
                                      },
                                    }
                                  : s,
                              ),
                            });
                          }}
                        />
                        <button
                          type="button"
                          aria-label={`Remove joint ${n + 1} from step ${j + 1}`}
                          disabled={disabled}
                          onClick={() =>
                            update(i, {
                              steps: c.steps.map((s, k) =>
                                k === j
                                  ? {
                                      ...s,
                                      values: Object.fromEntries(
                                        Object.entries(s.values).filter(
                                          ([v]) => v !== key,
                                        ),
                                      ),
                                    }
                                  : s,
                              ),
                            })
                          }
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                    {["move", "increment"].includes(step.operation) &&
                      Object.keys(step.values).length <
                        Object.keys(joints).length && (
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={() => {
                            const key = Object.keys(joints).find(
                              (key) => !(key in step.values),
                            )!;
                            update(i, {
                              steps: c.steps.map((s, k) =>
                                k === j
                                  ? {
                                      ...s,
                                      values: {
                                        ...s.values,
                                        [key]:
                                          step.operation === "increment"
                                            ? 0
                                            : robot.instance
                                                .initial_configuration
                                                .actuator_positions[key],
                                      },
                                    }
                                  : s,
                              ),
                            });
                          }}
                        >
                          Add joint target
                        </button>
                      )}
                  </div>
                ))}
                <button
                  type="button"
                  className="secondary"
                  disabled={disabled || c.steps.length >= 16}
                  onClick={() =>
                    update(i, {
                      steps: [
                        ...c.steps,
                        { operation: "feedback", values: {}, duration: 0.5 },
                      ],
                    })
                  }
                >
                  <Plus size={13} /> Add step
                </button>
              </>
            )}
            <button
              type="button"
              className="danger text-button"
              disabled={disabled}
              onClick={() => onChange(commands.filter((_, k) => k !== i))}
            >
              <Trash2 size={13} /> Remove command
            </button>
          </div>
        </details>
      ))}
    </section>
  );
}

import {randomId} from "./id";
import { useEffect, useState } from "react";
import { Focus, Scan } from "lucide-react";
import { api } from "./api";
import type { ProjectDetail, RobotWorkspace, WorkspaceOverlay } from "./types";
const colors = [
  "#7fbfe4",
  "#daa77e",
  "#b8ce80",
  "#c39bd7",
  "#78c8b2",
  "#e0c479",
  "#d68f9a",
  "#8f9fe0",
];

export function useRobotWorkspace(detail: ProjectDetail) {
  const [visible, setVisible] = useState(false),
    [robotId, setRobotId] = useState(detail.robots[0].instance.instance.id);
  const [data, setData] = useState<WorkspaceOverlay[]>([]),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [focus, setFocus] = useState("");
  // Feedback refreshes do not change reach. Only saved model geometry, limits and placements do.
  const configuration = JSON.stringify(
    detail.robots.map((r) => ({
      id: r.instance.instance.id,
      model: r.model.robot,
      actuators: r.model.actuators,
      kinematics: r.model.kinematics,
      base: r.instance.base_pose,
    })),
  );
  useEffect(() => {
    setVisible(false);
    setRobotId(detail.robots[0].instance.instance.id);
    setData([]);
    setError("");
  }, [detail.project.id]);
  useEffect(() => {
    if (!visible) {
      setData([]);
      setLoading(false);
      return;
    }
    const abort = new AbortController();
    setLoading(true);
    setError("");
    setData([]);
    const robots = detail.robots.filter(
      (r) => robotId === "all" || r.instance.instance.id === robotId,
    );
    void Promise.all(
      robots.map(async (r) => {
        const result = await api<RobotWorkspace>(
          `/projects/${detail.project.id}/robots/${r.instance.instance.id}/workspace`,
          { signal: abort.signal },
        );
        return {
          ...result,
          color: colors[detail.robots.indexOf(r) % colors.length],
        };
      }),
    )
      .then((result) => {
        if (!abort.signal.aborted) {
          setData(result);
          setFocus(randomId());
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [visible, robotId, detail.project.id, configuration]);
  const overlay = visible ? data.filter((d) => d.available) : [];
  return {
    visible,
    overlay,
    focus: visible ? focus : undefined,
    controls: (
      <section
        className="robot-workspace-controls"
        aria-label="Robot reachable workspace"
      >
        <div className="reach-toolbar">
          <button
            className={visible ? "secondary active" : "secondary"}
            aria-label={
              visible ? "Hide robot workspace" : "Show robot workspace"
            }
            aria-pressed={visible}
            onClick={() => setVisible(!visible)}
          >
            <Scan size={14} /> Robot workspace
          </button>
          {visible && (
            <>
              <label>
                Robot
                <select
                  aria-label="Workspace robot"
                  value={robotId}
                  onChange={(e) => setRobotId(e.target.value)}
                >
                  <option value="all">All project robots</option>
                  {detail.robots.map((r) => (
                    <option
                      key={r.instance.instance.id}
                      value={r.instance.instance.id}
                    >
                      {r.instance.instance.name} · {r.instance.instance.id}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="secondary"
                aria-label="Fit robot workspace"
                disabled={loading || !overlay.length}
                onClick={() => setFocus(randomId())}
              >
                <Focus size={13} /> Fit view
              </button>
              <span className="reach-label">
                Sampled tool reach · world / m
              </span>
            </>
          )}
          {!visible && (
            <span className="reach-label">
              See where a robot’s tool can reach.
            </span>
          )}
        </div>
        {visible && (
          <div className="reach-details" role="status">
            {loading ? (
              <span>Calculating workspace…</span>
            ) : error ? (
              <span className="inline-error" role="alert">{error}</span>
            ) : (
              data.map((d) => (
                <div
                  key={d.robot_id}
                  className="reach-legend"
                  data-workspace-robot={d.robot_id}
                  data-workspace-available={d.available}
                >
                  <i style={{ background: d.color }} />
                  <strong>{d.name}</strong>
                  <span>
                    {d.available
                      ? `${d.sample_count.toLocaleString()} tool positions`
                      : d.reason}
                  </span>
                  {d.bounds && (
                    <small>
                      {(["X", "Y", "Z"] as const)
                        .map(
                          (a, i) =>
                            `${a} ${d.bounds!.min[i].toFixed(2)}…${d.bounds!.max[i].toFixed(2)} m`,
                        )
                        .join(" · ")}
                    </small>
                  )}
                </div>
              ))
            )}
            <p>
              Joint limits and table clearance included. Obstacles,
              self-collision, other robots and tool orientation can reduce
              usable reach. Compile a plan to check the motion.
            </p>
          </div>
        )}
      </section>
    ),
  };
}

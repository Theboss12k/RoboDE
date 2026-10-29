import Feedback from "../../SERVER_CLIENT/client/src/ui/Feedback";
import {randomId} from "../../SERVER_CLIENT/client/src/id";
import NvidiaLogo from "../../SERVER_CLIENT/client/src/branding/NvidiaLogo";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  Camera,
  Check,
  Download,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
  ScanLine,
} from "lucide-react";
import type { WorldObject } from "../../SERVER_CLIENT/client/src/types";
import type { Room, Workspace } from "./types";
import { api, post, route } from "./api";
import RoomCamera from "./RoomCamera";
import GpuStart from "./GpuStart";
export default function Rooms({
  workspace,
  onBack,
  onRefresh,
}: {
  workspace: Workspace;
  onBack: () => void;
  onRefresh: () => void;
}) {
  const [rooms, setRooms] = useState<Room[]>([]),
    [room, setRoom] = useState<Room | null>(null),
    [name, setName] = useState("My room");
  const [worker, setWorker] = useState<{ ready: boolean; message?: string }>({
    ready: false,
  });
  const [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const [scale, setScale] = useState(1),
    [translation, setTranslation] = useState({ x: 0, y: 0, z: 0 }),
    [yaw, setYaw] = useState(0),
    [reviewed, setReviewed] = useState(false);
  const [camera, setCamera] = useState(false);
  const [assets, setAssets] = useState<WorldObject[]>([]);
  const base = route(workspace.project.id);
  const load = () => api<Room[]>(base + "/rooms").then(setRooms);
  useEffect(() => {
    let alive = true;
    load().catch((e) => {
      if (alive) setError(e.message);
    });
    api<{ ready: boolean; message?: string }>("/rooms/status")
      .then((v) => {
        if (alive) setWorker(v);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [base]);
  useEffect(() => {
    if (room?.status !== "reconstructing") return;
    const timer = setInterval(
      () =>
        api<Room>(base + "/rooms/" + room.id)
          .then(setRoom)
          .catch((e) => setError(e.message)),
      3000,
    );
    return () => clearInterval(timer);
  }, [base, room?.id, room?.status]);
  async function work(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  function choose(r: Room) {
    setCamera(false);
    setRoom(r);
    setAssets(r.alignment?.assets ?? []);
    setScale(r.alignment?.metres_per_unit ?? 1);
    setTranslation(r.alignment?.translation ?? { x: 0, y: 0, z: 0 });
    setYaw(r.alignment?.yaw_degrees ?? 0);
    setReviewed(false);
    setError("");
  }
  useEffect(() => {
    if (room?.id && window.innerWidth < 850)
      requestAnimationFrame(() =>
        document.querySelector(".room-content")?.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? "instant"
            : "smooth",
          block: "start",
        }),
      );
  }, [room?.id]);
  const current =
    room?.status === "capture"
      ? 0
      : room?.status === "reconstructing"
        ? 1
        : room?.status === "deployed"
          ? 3
          : 2;
  return (
    <main className="rooms-page">
      <button className="back-button" onClick={onBack}>
        <ArrowLeft size={18} /> Back to workspace
      </button>
      <div className="page-heading">
        <div>
          <span className="overline">REAL ROOM → DIGITAL WORKSPACE</span>
          <h1>Bring your room into the workspace.</h1>
          <p>
            Capture it with photos, reconstruct it with NVIDIA NuRec, then align
            it in Isaac Sim.
          </p>
        </div>
        <div className="nvidia-tool-heading nurec-brand">
          <NvidiaLogo />
          <span>NuRec</span>
        </div>
      </div>
      <div className="room-layout">
        <aside className="panel room-list">
          <h2>Your room captures</h2>
          <a className="download-link" href="/business/room-capture.html" target="_blank" rel="noreferrer">Offline capture · export photos for desktop import ↗</a>
          <label>
            Room name
            <input
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              placeholder="Packaging room"
            />
          </label>
          <button
            className="primary"
            disabled={!!busy || !name.trim()}
            onClick={() =>
              void work("Creating capture", async () =>
                choose(await post<Room>(base + "/rooms", { name })),
              )
            }
          >
            <Plus size={18} /> New room capture
          </button>
          {rooms.map((r) => (
            <button
              className={`room-choice ${room?.id === r.id ? "active" : ""}`}
              key={r.id}
              onClick={() => choose(r)}
            >
              <Camera size={20} />
              <span>
                <strong>{r.name}</strong>
                <small>
                  {r.status === "deployed" ? "Available in Isaac Sim" : r.stage}
                </small>
              </span>
            </button>
          ))}
          <div className="callout">
            <div className="nvidia-tool-heading">
              <NvidiaLogo />
              <strong>GPU reconstruction service</strong>
            </div>
            {!worker.ready && (
              <GpuStart
                onReady={async () => {
                  if (workspace.backend === "isaac_sim") {
                    await post(base + "/connect");
                    onRefresh();
                  }
                  setWorker(await api("/rooms/status"));
                }}
              />
            )}
            <p>
              {worker.ready
                ? "Connected and ready for your photos."
                : (worker.message ?? "Checking connection…")}
            </p>
            <button
              className="text-button"
              onClick={() =>
                void work("Checking GPU service", async () =>
                  setWorker(await api("/rooms/status")),
                )
              }
            >
              <RefreshCw size={15} /> Check connection
            </button>
          </div>
          <a
            href="https://docs.nvidia.com/nurec/robotics/neural_reconstruction_mono.html"
            target="_blank"
            rel="noreferrer"
          >
            NVIDIA capture guide ↗
          </a>
        </aside>
        <section className="panel room-content">
          {!room ? (
            <div className="friendly-empty">
              <Camera size={54} />
              <h2>A familiar room. A new way to work.</h2>
              <p>
                Create a room capture to begin, or import a room you have
                already reconstructed.
              </p>
              <p>
                Take overlapping photos around the room at several heights. Keep
                the room still, with steady lighting. Capture the empty room
                where possible; movable items need their own named simulation
                objects.
              </p>
            </div>
          ) : (
            <>
              <div className="room-title">
                <h2>{room.name}</h2>
                <span className="soft-badge">{room.stage}</span>
              </div>
              <ol className="capture-steps">
                {[
                  "Capture",
                  "Reconstruct",
                  "Align & name",
                  "Use in Isaac Sim",
                ].map((s, i) => (
                  <li key={s} className={i <= current ? "active" : ""}>
                    <span>{i < current ? <Check size={14} /> : i + 1}</span>
                    {s}
                  </li>
                ))}
              </ol>
              {["capture", "failed", "cancelled"].includes(room.status) && (
                <div className="capture-stage">
                  <h3>Start with a walk around your room.</h3>
                  <p>
                    Add at least 12 overlapping JPG/PNG photos. A thorough
                    capture normally needs more, including corners, floors and
                    several camera heights. Use one camera with the same lens
                    and locked focus/exposure.
                  </p>
                  <button
                    className="primary"
                    disabled={!!busy}
                    onClick={() => setCamera(true)}
                  >
                    <Camera size={20} /> Open phone camera
                  </button>
                  {camera && (
                    <RoomCamera
                      onClose={() => setCamera(false)}
                      onPhoto={async (photo) => {
                        setRoom(
                          await api(
                            base +
                              "/rooms/" +
                              room.id +
                              "/photos?filename=capture.jpg",
                            {
                              method: "PUT",
                              body: photo,
                              headers: { "Content-Type": "image/jpeg" },
                            },
                          ),
                        );
                        await load();
                      }}
                    />
                  )}
                  <div className="upload-tiles">
                    <label className="upload-tile">
                      <Camera size={26} />
                      <strong>Add room photos</strong>
                      <span>{room.photos} photos added · 12 MB per photo</span>
                      <input
                        aria-label="Upload room photos"
                        type="file"
                        accept="image/jpeg,image/png"
                        multiple
                        disabled={!!busy}
                        onChange={(e) => {
                          const files = Array.from(e.target.files ?? []);
                          e.target.value = "";
                          void work("Uploading photographs", async () => {
                            for (const [i, file] of files.entries()) {
                              setBusy(
                                `Uploading photo ${i + 1} of ${files.length}`,
                              );
                              setRoom(
                                await api(
                                  base +
                                    "/rooms/" +
                                    room.id +
                                    "/photos?filename=" +
                                    encodeURIComponent(file.name),
                                  {
                                    method: "PUT",
                                    body: file,
                                    headers: { "Content-Type": file.type },
                                  },
                                ),
                              );
                            }
                          });
                        }}
                      />
                    </label>
                    <label className="upload-tile">
                      <Upload size={26} />
                      <strong>Already reconstructed?</strong>
                      <span>Import a NuRec USDZ package · up to 1 GB</span>
                      <input
                        aria-label="Import reconstructed room"
                        type="file"
                        accept=".usdz"
                        disabled={!!busy}
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          e.target.value = "";
                          if (file)
                            void work(
                              "Importing reconstructed room",
                              async () =>
                                setRoom(
                                  await api(
                                    base + "/rooms/" + room.id + "/scene",
                                    {
                                      method: "PUT",
                                      body: file,
                                      headers: {
                                        "Content-Type": "model/vnd.usdz+zip",
                                      },
                                    },
                                  ),
                                ),
                            );
                        }}
                      />
                    </label>
                  </div>
                  <button
                    className="primary"
                    disabled={!!busy || room.photos < 12 || !worker.ready}
                    onClick={() =>
                      void work("Sending photos to GPU", async () =>
                        setRoom(
                          await post(
                            base + "/rooms/" + room.id + "/reconstruct",
                          ),
                        ),
                      )
                    }
                  >
                    <ScanLine size={18} /> Reconstruct room
                  </button>
                  {!worker.ready && (
                    <p className="muted">
                      Your photos can be saved now. An administrator needs to
                      connect the GPU reconstruction worker to start processing.
                    </p>
                  )}
                  {room.error && <p className="error-note">{room.error}</p>}
                </div>
              )}
              {room.status === "reconstructing" && (
                <div className="friendly-empty">
                  <div className="spinner" />
                  <h3>{room.stage}</h3>
                  <p>
                    The GPU worker is estimating camera positions and training
                    the room reconstruction. Larger rooms can take hours. You
                    can return to the workspace and check here later.
                  </p>
                  <button
                    onClick={() =>
                      void work("Cancelling reconstruction", async () =>
                        setRoom(
                          await api(
                            base + "/rooms/" + room.id + "/reconstruction",
                            { method: "DELETE" },
                          ),
                        ),
                      )
                    }
                  >
                    Cancel reconstruction
                  </button>
                </div>
              )}
              {["align", "deployed"].includes(room.status) && (
                <div className="alignment-stage">
                  <div className="callout">
                    <strong>Make it look right. Then make it usable.</strong>
                    <p>
                      NuRec reconstructs visual geometry. It does not
                      automatically create named tables, movable objects or
                      collision shapes. Reference the scan in Isaac Sim, verify
                      its real-world scale and floor, and name the simple boxes
                      below for planning.
                    </p>
                    <a
                      className="download-link"
                      href={
                        "/api/business" + base + "/rooms/" + room.id + "/scene"
                      }
                    >
                      <Download size={16} /> Download room USDZ for inspection
                    </a>
                  </div>
                  <h3>1. Align the captured room</h3>
                  <div className="form-grid">
                    <label>
                      Metres per scan unit
                      <input
                        aria-label="Room metric scale"
                        type="number"
                        min=".00001"
                        step=".01"
                        value={scale}
                        onChange={(e) => {
                          setScale(Number(e.target.value));
                          setReviewed(false);
                        }}
                      />
                    </label>
                    <label>
                      Room rotation · degrees
                      <input
                        type="number"
                        step="1"
                        value={yaw}
                        onChange={(e) => {
                          setYaw(Number(e.target.value));
                          setReviewed(false);
                        }}
                      />
                    </label>
                    {(["x", "y", "z"] as const).map((a) => (
                      <label key={a}>
                        Offset {a.toUpperCase()} · metres
                        <input
                          type="number"
                          step=".01"
                          value={translation[a]}
                          onChange={(e) => {
                            setTranslation({
                              ...translation,
                              [a]: Number(e.target.value),
                            });
                            setReviewed(false);
                          }}
                        />
                      </label>
                    ))}
                  </div>
                  <p className="muted">
                    Measure a real distance in the room and the same distance in
                    the scan: metres per unit = real metres ÷ scan distance. Set
                    the floor to Z = 0. Proxy coordinates below are already
                    world metres.
                  </p>
                  <h3>2. Name the assets people will use</h3>
                  {assets.map((a, i) => (
                    <div className="proxy-card" key={a.id}>
                      <div className="proxy-top">
                        <label>
                          Asset name
                          <input
                            aria-label={`Room asset ${i + 1} name`}
                            value={a.name}
                            onChange={(e) => {
                              setAssets(
                                assets.map((o, j) =>
                                  j === i ? { ...o, name: e.target.value } : o,
                                ),
                              );
                              setReviewed(false);
                            }}
                          />
                        </label>
                        <label>
                          Use as
                          <select
                            value={a.kind}
                            onChange={(e) => {
                              setAssets(
                                assets.map((o, j) =>
                                  j === i
                                    ? {
                                        ...o,
                                        kind: e.target
                                          .value as WorldObject["kind"],
                                      }
                                    : o,
                                ),
                              );
                              setReviewed(false);
                            }}
                          >
                            <option value="obstacle">
                              Table / fixed obstacle
                            </option>
                            <option value="region">Destination area</option>
                            <option value="object">Movable item</option>
                          </select>
                        </label>
                        <button
                          aria-label={`Remove room asset ${i + 1}`}
                          onClick={() => {
                            setAssets(assets.filter((o) => o.id !== a.id));
                            setReviewed(false);
                          }}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                      <div className="form-grid">
                        {(["position", "size"] as const).flatMap((key) =>
                          (["x", "y", "z"] as const).map((axis) => (
                            <label key={key + axis}>
                              {key === "size" ? "Size" : "Centre"}{" "}
                              {axis.toUpperCase()} · m
                              <input
                                type="number"
                                step=".01"
                                min={key === "size" ? ".001" : undefined}
                                value={a[key][axis]}
                                onChange={(e) => {
                                  setAssets(
                                    assets.map((o, j) =>
                                      j === i
                                        ? {
                                            ...o,
                                            [key]: {
                                              ...o[key],
                                              [axis]: Number(e.target.value),
                                            },
                                          }
                                        : o,
                                    ),
                                  );
                                  setReviewed(false);
                                }}
                              />
                            </label>
                          )),
                        )}
                        {a.kind === "object" && (
                          <label>
                            Mass · kg
                            <input
                              type="number"
                              min=".001"
                              step=".01"
                              value={a.mass_kg}
                              onChange={(e) =>
                                setAssets(
                                  assets.map((o, j) =>
                                    j === i
                                      ? {
                                          ...o,
                                          mass_kg: Number(e.target.value),
                                        }
                                      : o,
                                  ),
                                )
                              }
                            />
                          </label>
                        )}
                      </div>
                    </div>
                  ))}
                  <button
                    className="secondary"
                    onClick={() => {
                      const n = assets.length + 1;
                      setAssets([
                        ...assets,
                        {
                          id:
                            "room_" +
                            room.id.slice(0, 8) +
                            "_" +
                            randomId().slice(0, 8),
                          name: "Table" + n,
                          kind: "obstacle",
                          position: { x: 0.35, y: 0.2, z: 0.1 },
                          size: { x: 0.2, y: 0.2, z: 0.2 },
                          mass_kg: 0,
                        },
                      ]);
                      setReviewed(false);
                    }}
                  >
                    <Plus size={18} /> Add named room asset
                  </button>
                  <label className="review-check">
                    <input
                      type="checkbox"
                      checked={reviewed}
                      onChange={(e) => setReviewed(e.target.checked)}
                    />{" "}
                    I verified the room scale, floor alignment, and named
                    collision boxes in Isaac Sim.
                  </label>
                  <button
                    className="primary"
                    disabled={
                      !!busy ||
                      !reviewed ||
                      !assets.length ||
                      !workspace.can_deploy_room
                    }
                    onClick={() =>
                      void work("Loading room into Isaac Sim", async () => {
                        setRoom(
                          await post(base + "/rooms/" + room.id + "/deploy", {
                            metres_per_unit: scale,
                            translation,
                            yaw_degrees: yaw,
                            assets,
                            reviewed,
                          }),
                        );
                        onRefresh();
                      })
                    }
                  >
                    <Check size={18} /> Use room in this workspace
                  </button>
                  {!workspace.can_deploy_room && (
                    <p className="muted">
                      A managed Isaac Sim connection with room loading enabled
                      is required. Ask the workspace administrator to connect it
                      in RoboDE.
                    </p>
                  )}
                </div>
              )}
            </>
          )}
          {busy && (
            <p className="busy-message" role="status">
              <span className="spinner small" />
              {busy}
            </p>
          )}
          <Feedback message={error} />
        </section>
      </div>
    </main>
  );
}

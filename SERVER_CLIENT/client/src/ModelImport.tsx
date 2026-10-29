import Feedback from "./ui/Feedback";
import {randomId} from "./id";
import { useState } from "react";
import { Upload, LoaderCircle } from "lucide-react";
import { api } from "./api";
import type { ModelAsset, WorldObject } from "./types";
import {
  MAX_MODEL_BYTES,
  modelFormat,
  parseModel,
  disposeModel,
} from "./modelAssets";
export default function ModelImport({
  projectId,
  disabled,
  onAdd,
  onBusy,
}: {
  projectId: string;
  disabled: boolean;
  onAdd: (object: WorldObject) => void;
  onBusy: (busy: boolean) => void;
}) {
  const [open, setOpen] = useState(false),
    [file, setFile] = useState<File | null>(null);
  const [axis, setAxis] = useState<"Y" | "Z">("Y");
  const [kind, setKind] = useState<"object" | "obstacle">("object");
  const [length, setLength] = useState(0.15),
    [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null),
    [notice, setNotice] = useState<string | null>(null);
  async function importModel() {
    if (!file) return;
    setError(null);
    setNotice(null);
    setWorking(true);
    onBusy(true);
    try {
      if (file.size > MAX_MODEL_BYTES)
        throw new Error("Model files must be at most 25 MB.");
      if (!Number.isFinite(length) || length < 0.001 || length > 10)
        throw new Error(
          "Set the longest dimension between 0.001 and 10 metres.",
        );
      const format = modelFormat(file.name);
      const parsed = await parseModel(await file.arrayBuffer(), format, axis);
      const largest = Math.max(parsed.size.x, parsed.size.y, parsed.size.z);
      const size = {
        x: Math.max(0.001, (parsed.size.x * length) / largest),
        y: Math.max(0.001, (parsed.size.y * length) / largest),
        z: Math.max(0.001, (parsed.size.z * length) / largest),
      };
      disposeModel(parsed.scene);
      const asset = await api<ModelAsset>(
        `/projects/${projectId}/assets?filename=${encodeURIComponent(file.name)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        },
      );
      onAdd({
        id: `mesh_${randomId().replaceAll("-", "").slice(0, 12)}`,
        name: file.name.replace(/\.[^.]+$/, ""),
        kind,
        position: { x: 0.2, y: 0.4, z: Math.max(0.1, size.z / 2 + 0.01) },
        size,
        mass_kg: kind === "object" ? 0.05 : 0,
        mesh: {
          asset_id: asset.id,
          format: asset.format,
          filename: asset.filename,
          up_axis: axis,
        },
      });
      setNotice(
        `${file.name} imported. Save scene to keep it in this environment.`,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setWorking(false);
      onBusy(false);
    }
  }
  return (
    <section className="model-import">
      <button
        className="secondary"
        disabled={disabled || working}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <Upload size={13} /> Import 3D object
      </button>
      {open && (
        <div className="model-import-form">
          <label className="field">
            Model file
            <input
              aria-label="3D model file"
              type="file"
              accept=".glb,.gltf,.obj,.stl"
              disabled={disabled || working}
              onChange={(e) => {
                const selected = e.target.files?.[0] ?? null;
                setFile(selected);
                setError(null);
                setNotice(null);
                if (selected)
                  setAxis(
                    selected.name.toLowerCase().endsWith(".stl") ? "Z" : "Y",
                  );
              }}
            />
          </label>
          <div className="import-options">
            <label className="field">
              Scene role
              <select
                aria-label="Imported model role"
                value={kind}
                disabled={disabled || working}
                onChange={(e) => setKind(e.target.value as typeof kind)}
              >
                <option value="object">Movable object</option>
                <option value="obstacle">Obstacle</option>
              </select>
            </label>
            <label className="field">
              Source up axis
              <select
                aria-label="Model up axis"
                value={axis}
                disabled={disabled || working}
                onChange={(e) => setAxis(e.target.value as typeof axis)}
              >
                <option value="Y">Y up</option>
                <option value="Z">Z up</option>
              </select>
            </label>
          </div>
          <label className="field">
            Longest dimension · metres
            <input
              aria-label="Model longest dimension"
              type="number"
              min=".001"
              max="10"
              step=".01"
              value={length}
              disabled={disabled || working}
              onChange={(e) => setLength(Number(e.target.value))}
            />
          </label>
          <p>
            GLB or embedded glTF preserves materials and embedded textures.
            OBJ/STL imports geometry. Maximum 25 MB. Set position and dimensions
            below after import.
          </p>
          <button
            className="primary"
            disabled={!file || disabled || working}
            onClick={() => void importModel()}
          >
            {working ? (
              <LoaderCircle className="spin" size={13} />
            ) : (
              <Upload size={13} />
            )}{" "}
            {working ? "Importing model…" : "Import model"}
          </button>
          <Feedback message={error} />
          {notice && (
            <p className="model-import-notice" role="status">
              {notice}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

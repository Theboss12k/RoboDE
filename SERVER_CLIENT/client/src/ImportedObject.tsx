import { useEffect, useState } from "react";
import { Html } from "@react-three/drei";
import type * as THREE from "three";
import type { WorldObject } from "./types";
import { assetURL, parseModel, disposeModel } from "./modelAssets";

export default function ImportedObject({
  object,
  projectId,
  onStatus,
}: {
  object: WorldObject;
  projectId?: string;
  onStatus?: (id: string, status: "loading" | "loaded" | "error") => void;
}) {
  const [model, setModel] = useState<THREE.Group | null>(null);
  const [error, setError] = useState(false);
  const mesh = object.mesh!;
  useEffect(() => {
    const abort = new AbortController();
    let loaded: THREE.Group | null = null;
    setModel(null);
    setError(false);
    onStatus?.(object.id, "loading");
    if (!projectId) {
      setError(true);
      onStatus?.(object.id, "error");
      return;
    }
    void fetch(assetURL(projectId, mesh.asset_id), { signal: abort.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Model asset is unavailable");
        const parsed = await parseModel(
          await response.arrayBuffer(),
          mesh.format,
          mesh.up_axis,
        );
        if (abort.signal.aborted) disposeModel(parsed.scene);
        else {
          loaded = parsed.scene;
          setModel(loaded);
          onStatus?.(object.id, "loaded");
        }
      })
      .catch(() => {
        if (!abort.signal.aborted) {
          setError(true);
          onStatus?.(object.id, "error");
        }
      });
    return () => {
      abort.abort();
      if (loaded) disposeModel(loaded);
    };
  }, [
    projectId,
    mesh.asset_id,
    mesh.format,
    mesh.up_axis,
    object.id,
    onStatus,
  ]);
  return (
    <group name={`imported-${object.id}`}>
      {model ? (
        <group scale={[object.size.x, object.size.z, object.size.y]}>
          <primitive object={model} />
        </group>
      ) : (
        <mesh>
          <boxGeometry args={[object.size.x, object.size.z, object.size.y]} />
          <meshBasicMaterial
            color={error ? "#e29b7a" : "#a6bd87"}
            wireframe
            transparent
            opacity={0.5}
          />
        </mesh>
      )}
      {error && (
        <Html center>
          <span className="model-load-error" role="status">
            {object.name}: model unavailable
          </span>
        </Html>
      )}
    </group>
  );
}

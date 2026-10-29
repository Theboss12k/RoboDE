import { useEffect, useMemo } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { WorkspaceOverlay as Envelope } from "./types";
function PointCloud({ workspace }: { workspace: Envelope }) {
  const positions = useMemo(
    () => new Float32Array(workspace.points.flatMap(([x, y, z]) => [x, z, -y])),
    [workspace.points],
  );
  return (
    <points
      name={`reachable-workspace-${workspace.robot_id}`}
      frustumCulled={false}
      raycast={() => {}}
    >
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        color={workspace.color}
        size={0.007}
        transparent
        opacity={0.22}
        depthWrite={false}
        sizeAttenuation
      />
    </points>
  );
}
export default function WorkspaceOverlay({
  workspaces,
  focusRequest,
}: {
  workspaces: Envelope[];
  focusRequest?: string;
}) {
  const camera = useThree((s) => s.camera),
    controls = useThree((s) => s.controls),
    size = useThree((s) => s.size);
  const bounds = JSON.stringify(workspaces.map((w) => w.bounds));
  useEffect(() => {
    if (!focusRequest || !workspaces.length) return;
    const box = new THREE.Box3();
    for (const w of workspaces)
      if (w.bounds) {
        const { min, max } = w.bounds;
        box.expandByPoint(new THREE.Vector3(min[0], min[2], -max[1]));
        box.expandByPoint(new THREE.Vector3(max[0], max[2], -min[1]));
      }
    if (box.isEmpty()) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const vertical = THREE.MathUtils.degToRad(
      camera instanceof THREE.PerspectiveCamera ? camera.fov : 37,
    );
    const horizontal =
      2 *
      Math.atan(
        (Math.tan(vertical / 2) * size.width) / Math.max(size.height, 1),
      );
    const distance = Math.max(
      0.4,
      (sphere.radius / Math.sin(Math.min(vertical, horizontal) / 2)) * 1.1,
    );
    camera.position.copy(
      sphere.center
        .clone()
        .add(
          new THREE.Vector3(1, 0.65, 1).normalize().multiplyScalar(distance),
        ),
    );
    const orbit = controls as unknown as {
      target?: THREE.Vector3;
      update?: () => void;
    };
    orbit?.target?.copy(sphere.center);
    camera.lookAt(sphere.center);
    orbit?.update?.();
  }, [camera, controls, focusRequest, bounds, size.width, size.height]);
  return (
    <group>
      {workspaces.map((w) => (
        <PointCloud key={w.robot_id} workspace={w} />
      ))}
    </group>
  );
}

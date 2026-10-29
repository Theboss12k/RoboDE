import {
  Component,
  useMemo,
  useEffect,
  useRef,
  type ReactNode,
  Suspense,
} from "react";
import {
  Canvas,
  useFrame,
  useThree,
  type ThreeEvent,
} from "@react-three/fiber";
import {
  TransformControls,
  ContactShadows,
  Grid,
  Line,
  OrbitControls,
  Html,
} from "@react-three/drei";
import * as THREE from "three";
import { createRoot, type Root } from "react-dom/client";
import WorkspaceOverlay from "./WorkspaceOverlay";
import type { WorkspaceOverlay as Envelope } from "./types";
import ImportedObject from "./ImportedObject";
import type { Frame, Model, WorldObject, CellRobot } from "./types";

const vector = ({ x, y, z }: { x: number; y: number; z: number }) =>
  new THREE.Vector3(x, z, -y);
// A projected DOM label with deferred root cleanup, including React strict-mode remounts.
function RobotLabel({
  position,
  children,
}: {
  position: THREE.Vector3 | [number, number, number];
  children: ReactNode;
}) {
  const anchor = useRef<THREE.Group>(null),
    element = useRef<HTMLDivElement | null>(null),
    root = useRef<Root | null>(null);
  const { gl, camera, size } = useThree();
  useEffect(() => {
    const div = document.createElement("div");
    div.className = "projected-robot-label";
    gl.domElement.parentElement?.appendChild(div);
    const mounted = createRoot(div);
    element.current = div;
    root.current = mounted;
    return () => {
      div.remove();
      element.current = null;
      root.current = null;
      queueMicrotask(() => mounted.unmount());
    };
  }, [gl]);
  useEffect(() => {
    root.current?.render(children);
  }, [children]);
  useFrame(() => {
    if (!anchor.current || !element.current) return;
    anchor.current.updateWorldMatrix(true, false);
    const v = anchor.current
        .getWorldPosition(new THREE.Vector3())
        .project(camera),
      div = element.current;
    div.style.display =
      v.z < -1 || v.z > 1 || Math.abs(v.x) > 1 || Math.abs(v.y) > 1
        ? "none"
        : "";
    div.style.left = `${((v.x + 1) * size.width) / 2}px`;
    div.style.top = `${((1 - v.y) * size.height) / 2}px`;
  });
  return <group ref={anchor} position={position} />;
}

function Link({
  a,
  b,
  radius = 0.025,
  color = "#b8c0ba",
  onClick,
}: {
  a: THREE.Vector3;
  b: THREE.Vector3;
  radius?: number;
  color?: string;
  onClick?: (event: ThreeEvent<MouseEvent>) => void;
}) {
  const direction = b.clone().sub(a);
  const quaternion = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction.clone().normalize(),
  );
  return (
    <mesh
      position={a.clone().add(b).multiplyScalar(0.5)}
      quaternion={quaternion}
      castShadow
      receiveShadow
      onClick={onClick}
    >
      <cylinderGeometry
        args={[radius, radius * 1.15, direction.length(), 20]}
      />
      <meshStandardMaterial color={color} roughness={0.35} metalness={0.5} />
    </mesh>
  );
}
export function Robot({
  model,
  q,
  selectedPart,
  onSelectPart,
}: {
  model: Model;
  q: Record<string, number>;
  selectedPart?: string;
  onSelectPart?: (part: string) => void;
}) {
  const pick = (part: string) => (event: ThreeEvent<MouseEvent>) => {
    if (onSelectPart) {
      event.stopPropagation();
      onSelectPart(part);
    }
  };
  const tag = (part: string, position: THREE.Vector3, title: string) =>
    onSelectPart && (
      <RobotLabel key={part} position={position}>
        <button
          className={`robot-part-tag ${selectedPart === part ? "selected" : ""}`}
          aria-label={`Select ${title}`}
          onClick={() => onSelectPart(part)}
        >
          {title}
        </button>
      </RobotLabel>
    );
  if (
    model.kinematics.solver === "serial_chain_dls_v1" &&
    model.kinematics.joints?.length
  )
    return (
      <SerialRobot
        model={model}
        q={q}
        selectedPart={selectedPart}
        onSelectPart={onSelectPart}
      />
    );
  if (
    model.planning_supported === false ||
    model.kinematics.solver !== "analytic_yaw_two_link_v1"
  )
    return (
      <group>
        <mesh position={[0, 0.1, 0]}>
          <boxGeometry args={[0.12, 0.2, 0.12]} />
          <meshStandardMaterial color="#87948b" wireframe />
        </mesh>
        <Html position={[0, 0.25, 0]} center>
          <span className="model-marker">
            {model.robot.name}
            <small>Model configuration · geometry unavailable</small>
          </span>
        </Html>
      </group>
    );
  const { base_height: h, upper_arm: a, forearm: b } = model.kinematics.links;
  const r1 = a * Math.cos(q.shoulder),
    z1 = h + a * Math.sin(q.shoulder);
  const r2 = r1 + b * Math.cos(q.shoulder + q.elbow),
    z2 = z1 + b * Math.sin(q.shoulder + q.elbow);
  const points = [
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, h, 0),
    vector({
      x: r1 * Math.cos(q.base_yaw),
      y: r1 * Math.sin(q.base_yaw),
      z: z1,
    }),
    vector({
      x: r2 * Math.cos(q.base_yaw),
      y: r2 * Math.sin(q.base_yaw),
      z: z2,
    }),
  ];
  return (
    <group>
      <mesh
        position={[0, 0.016, 0]}
        castShadow
        onClick={pick("actuator:base_yaw")}
      >
        <cylinderGeometry args={[0.075, 0.09, 0.032, 48]} />
        <meshStandardMaterial
          color="#4b5550"
          metalness={0.7}
          roughness={0.35}
        />
      </mesh>
      {points.slice(1).map((point, i) => (
        <Link
          key={i}
          a={points[i]}
          b={point}
          radius={i === 0 ? 0.046 : 0.027}
          color={i === 0 ? "#64716b" : "#b8c3b8"}
          onClick={pick(`actuator:${["base_yaw", "shoulder", "elbow"][i]}`)}
        />
      ))}
      {points.slice(1).map((point, i) => (
        <mesh
          key={i}
          position={point}
          castShadow
          onClick={pick(`actuator:${["shoulder", "elbow", "wrist"][i]}`)}
        >
          <sphereGeometry args={[i === 0 ? 0.049 : 0.038, 24, 24]} />
          <meshStandardMaterial
            color={
              selectedPart === `actuator:${["shoulder", "elbow", "wrist"][i]}`
                ? "#72adff"
                : "#70839e"
            }
            roughness={0.4}
            metalness={0.5}
          />
        </mesh>
      ))}
      <group
        position={points[3]}
        rotation={[0, q.base_yaw, q.shoulder + q.elbow + q.wrist]}
        onClick={pick(`effector:${model.capabilities.end_effector}`)}
      >
        <mesh
          position={[0, 0.005, 0]}
          castShadow
          onClick={pick("actuator:wrist")}
        >
          <boxGeometry args={[0.075, 0.025, 0.042]} />
          <meshStandardMaterial
            color="#333e37"
            metalness={0.6}
            roughness={0.3}
          />
        </mesh>
        {[-1, 1].map((sign) => (
          <mesh
            key={sign}
            position={[sign * (q.gripper / 2 + 0.006), -0.015, 0]}
            castShadow
            onClick={pick("actuator:gripper")}
          >
            <boxGeometry args={[0.01, 0.042, 0.028]} />
            <meshStandardMaterial
              color="#bbc4b9"
              metalness={0.7}
              roughness={0.3}
            />
          </mesh>
        ))}
      </group>
      {tag(
        "actuator:base_yaw",
        points[0].clone().add(new THREE.Vector3(-0.08, 0.06, 0)),
        "base_yaw",
      )}
      {tag(
        "actuator:shoulder",
        points[1].clone().add(new THREE.Vector3(0.07, 0.04, 0)),
        "shoulder",
      )}
      {tag(
        "actuator:elbow",
        points[2].clone().add(new THREE.Vector3(0, 0.07, 0)),
        "elbow",
      )}
      {tag(
        "actuator:wrist",
        points[3].clone().add(new THREE.Vector3(0, 0.12, 0)),
        "wrist",
      )}
      {tag(
        `effector:${model.capabilities.end_effector}`,
        points[3].clone().add(new THREE.Vector3(0, -0.08, 0)),
        model.capabilities.end_effector,
      )}
    </group>
  );
}
function SerialRobot({
  model,
  q,
  selectedPart,
  onSelectPart,
}: {
  model: Model;
  q: Record<string, number>;
  selectedPart?: string;
  onSelectPart?: (part: string) => void;
}) {
  const frames: Record<string, THREE.Matrix4> = {
    [model.kinematics.world_frame ?? "world"]: new THREE.Matrix4(),
  };
  const origin = (xyz: number[] = [0, 0, 0], rpy: number[] = [0, 0, 0]) =>
    new THREE.Matrix4().compose(
      new THREE.Vector3(...(xyz as [number, number, number])),
      new THREE.Quaternion().setFromEuler(
        new THREE.Euler(...(rpy as [number, number, number]), "ZYX"),
      ),
      new THREE.Vector3(1, 1, 1),
    );
  const point = (m: THREE.Matrix4) => {
    const v = new THREE.Vector3().setFromMatrixPosition(m);
    return vector(v);
  };
  const parts: ReactNode[] = [];
  for (const j of model.kinematics.joints ?? []) {
    const parent = frames[j.parent];
    if (!parent) continue;
    const start = parent.clone().multiply(origin(j.origin?.xyz, j.origin?.rpy));
    const motion = new THREE.Matrix4(),
      axis = new THREE.Vector3(
        ...((j.axis_vector ?? (j.axis === "x"
          ? [1, 0, 0]
          : j.axis === "y"
            ? [0, 1, 0]
            : [0, 0, 1])) as [number, number, number]),
      );
    if (j.type === "revolute")
      motion.makeRotationAxis(axis.normalize(), q[j.actuator ?? ""] ?? 0);
    if (j.type === "prismatic")
      motion.makeTranslation(axis.normalize().multiplyScalar(q[j.actuator ?? ""] ?? 0));
    const end = start.clone().multiply(motion);
    frames[j.child] = end;
    const part = `actuator:${j.actuator}`,
      selected = part === selectedPart;
    parts.push(
      <group
        key={j.child}
        onClick={(e) => {
          if (onSelectPart && j.actuator) {
            e.stopPropagation();
            onSelectPart(part);
          }
        }}
      >
        <Link
          a={point(parent)}
          b={point(start)}
          radius={0.017}
          color="#70839e"
        />
        <Link
          a={point(start)}
          b={point(end)}
          radius={0.023}
          color={selected ? "#72adff" : "#afbbcb"}
        />
        <mesh position={point(end)}>
          <sphereGeometry args={[0.028, 16, 16]} />
          <meshStandardMaterial color={selected ? "#72adff" : "#70839e"} />
        </mesh>
        {onSelectPart && j.actuator && (
          <RobotLabel position={point(end).add(new THREE.Vector3(0, 0.05, 0))}>
            <button
              className={`robot-part-tag ${selected ? "selected" : ""}`}
              onClick={() => onSelectPart(part)}
              aria-label={`Select ${j.actuator}`}
            >
              {j.actuator}
            </button>
          </RobotLabel>
        )}
      </group>,
    );
  }
  for (const [id, e] of Object.entries(model.kinematics.end_effectors ?? {})) {
    if (!frames[e.link]) continue;
    const toolFrame = frames[e.link].clone().multiply(origin(e.xyz, e.rpy));
    const basis = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
    const orientation = new THREE.Quaternion().setFromRotationMatrix(
      basis.clone().multiply(toolFrame).multiply(basis.clone().invert()),
    );
    const p = point(toolFrame),
      part = `effector:${id}`;
    const component = model.capabilities.components?.[id];
    const gap = component
      ? THREE.MathUtils.clamp(
          (q[component.actuator] - component.closed) /
            (component.open - component.closed),
          0,
          1,
        ) * 0.04
      : 0;
    parts.push(
      <group
        key={part}
        position={p}
        quaternion={orientation}
        onClick={(ev) => {
          if (onSelectPart) {
            ev.stopPropagation();
            onSelectPart(part);
          }
        }}
      >
        <mesh>
          <boxGeometry args={[0.06, 0.03, 0.04]} />
          <meshStandardMaterial
            color={selectedPart === part ? "#72adff" : "#c5d3e5"}
          />
        </mesh>
        {component &&
          [-1, 1].map((sign) => (
            <mesh
              key={sign}
              position={[sign * (gap + 0.006), -0.025, 0]}
              onClick={(ev) => {
                if (onSelectPart) {
                  ev.stopPropagation();
                  onSelectPart(`actuator:${component.actuator}`);
                }
              }}
            >
              <boxGeometry args={[0.01, 0.04, 0.028]} />
              <meshStandardMaterial color="#afc3df" />
            </mesh>
          ))}
        {onSelectPart && (
          <RobotLabel position={[0, -0.05, 0]}>
            <button
              className={`robot-part-tag ${selectedPart === part ? "selected" : ""}`}
              aria-label={`Select ${id}`}
              onClick={() => onSelectPart(part)}
            >
              {id}
            </button>
          </RobotLabel>
        )}
      </group>,
    );
  }
  return <group>{parts}</group>;
}

export type RobotBase = { x: number; y: number; z: number; yaw: number };
function EditableRobot({
  robot,
  q,
  selected,
  mode,
  onSelect,
  onTransform,
  disabled,
  showLabel,
}: {
  robot: CellRobot;
  q: Record<string, number>;
  selected: boolean;
  mode: "translate" | "rotate";
  onSelect?: (focus?: boolean) => void;
  onTransform?: (base: RobotBase) => void;
  disabled?: boolean;
  showLabel?:boolean;
}) {
  const group = useRef<THREE.Group>(null);
  const controls = useThree((s) => s.controls) as unknown as
    | { enabled: boolean }
    | undefined;
  const drag = useRef<{
    offset: THREE.Vector3;
    pointer: number;
    orbit: boolean;
  } | null>(null);
  const base = robot.instance.base_pose ?? { x: 0, y: 0, z: 0, yaw: 0 };
  useEffect(
    () => () => {
      if (controls && drag.current) controls.enabled = drag.current.orbit;
    },
    [controls],
  );
  const endDrag = (e: ThreeEvent<PointerEvent>) => {
    if (!drag.current) return;
    e.stopPropagation();
    if (controls) controls.enabled = drag.current.orbit;
    drag.current = null;
    (e.target as unknown as Element).releasePointerCapture?.(e.pointerId);
  };
  return (
    <>
      <group
        ref={group}
        position={vector(base)}
        rotation={[0, base.yaw, 0]}
        onClick={(e) => {
          if (onSelect) {
            e.stopPropagation();
            if (e.delta <= 4) onSelect(true);
          }
        }}
        onPointerDown={(e) => {
          if (!onSelect || disabled || e.button !== 0) return;
          e.stopPropagation();
          onSelect(false);
          if (mode !== "translate") return;
          const hit = e.ray.intersectPlane(
            new THREE.Plane(new THREE.Vector3(0, 1, 0), -base.z),
            new THREE.Vector3(),
          );
          if (!hit) return;
          drag.current = {
            offset: vector(base).sub(hit),
            pointer: e.pointerId,
            orbit: controls?.enabled ?? true,
          };
          if (controls) controls.enabled = false;
          (e.target as unknown as Element).setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!drag.current || !onTransform || disabled) return;
          e.stopPropagation();
          const hit = e.ray.intersectPlane(
            new THREE.Plane(new THREE.Vector3(0, 1, 0), -base.z),
            new THREE.Vector3(),
          );
          if (hit) {
            hit.add(drag.current.offset);
            onTransform({ ...base, x: hit.x, y: -hit.z });
          }
        }}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <Robot model={robot.model} q={q} />
        {selected && (
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.006, 0]}>
            <ringGeometry args={[0.105, 0.111, 64]} />
            <meshBasicMaterial color="#72adff" transparent opacity={0.85} />
          </mesh>
        )}
        {(onSelect || showLabel) && (
          <RobotLabel position={[0, 0.04, 0]}>
            <button
              aria-label={`Select robot ${robot.instance.instance.name}`}
              className={`scene-robot-label ${selected ? "selected" : ""}`}
              onClick={() => onSelect?.()}
            >
              {robot.instance.instance.name}
            </button>
          </RobotLabel>
        )}
      </group>
      {selected && onTransform && !disabled && (
        <TransformControls
          object={group as React.RefObject<THREE.Object3D>}
          mode={mode}
          space="world"
          size={1.5}
          showX={mode === "translate"}
          showY
          showZ={mode === "translate"}
          onObjectChange={() => {
            const g = group.current;
            if (g) {
              const heading = new THREE.Vector3(1, 0, 0).applyQuaternion(
                g.quaternion,
              );
              onTransform({
                x: g.position.x,
                y: -g.position.z,
                z: g.position.y,
                yaw: Math.atan2(-heading.z, heading.x),
              });
            }
          }}
        />
      )}
    </>
  );
}

function Apple({ position }: { position: THREE.Vector3 }) {
  return (
    <group position={position}>
      <mesh scale={[1, 0.95, 1]} castShadow>
        <sphereGeometry args={[0.0325, 32, 24]} />
        <meshStandardMaterial color="#b74831" roughness={0.4} />
      </mesh>
      <mesh position={[0.002, 0.034, 0]} rotation={[0, 0, -0.2]}>
        <cylinderGeometry args={[0.0025, 0.003, 0.018, 8]} />
        <meshStandardMaterial color="#4b3323" />
      </mesh>
      <mesh
        position={[0.01, 0.037, 0]}
        rotation={[0, 0, -0.5]}
        scale={[1, 0.25, 0.55]}
      >
        <sphereGeometry args={[0.012, 12, 8]} />
        <meshStandardMaterial color="#697e34" />
      </mesh>
    </group>
  );
}
function Basket({ object }: { object: WorldObject }) {
  const { x, y, z } = object.size;
  return (
    <group position={vector(object.position)}>
      <mesh position={[0, -z / 2 + 0.006, 0]} receiveShadow castShadow>
        <boxGeometry args={[x, 0.012, y]} />
        <meshStandardMaterial color="#91876a" roughness={0.8} />
      </mesh>
      {[-1, 1].map((s) => (
        <group key={s}>
          <mesh position={[(s * x) / 2, 0, 0]} castShadow>
            <boxGeometry args={[0.012, z, y]} />
            <meshStandardMaterial
              color="#8d8467"
              transparent
              opacity={0.6}
              roughness={0.8}
            />
          </mesh>
          <mesh position={[0, 0, (s * y) / 2]} castShadow>
            <boxGeometry args={[x, z, 0.012]} />
            <meshStandardMaterial
              color="#8d8467"
              transparent
              opacity={0.6}
              roughness={0.8}
            />
          </mesh>
          {[0, 1, 2].map((i) => (
            <group key={i}>
              <mesh position={[(s * x) / 2, -z / 2 + 0.025 + i * 0.04, 0]}>
                <boxGeometry args={[0.014, 0.007, y + 0.01]} />
                <meshStandardMaterial color="#c0ae7e" />
              </mesh>
              <mesh position={[0, -z / 2 + 0.025 + i * 0.04, (s * y) / 2]}>
                <boxGeometry args={[x + 0.01, 0.007, 0.014]} />
                <meshStandardMaterial color="#c0ae7e" />
              </mesh>
            </group>
          ))}
        </group>
      ))}
    </group>
  );
}
class SceneBoundary extends Component<
  { children: ReactNode },
  { error: boolean }
> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <div className="empty-state">
        <p>3D rendering is unavailable on this device.</p>
        <span>The task graph, code and runtime remain available.</span>
      </div>
    ) : (
      this.props.children
    );
  }
}
function FocusObject({
  object,
  request,
}: {
  object: WorldObject | undefined;
  request?: string;
}) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  useEffect(() => {
    if (!object || !request) return;
    const target = vector(object.position);
    const distance = Math.max(
      0.35,
      Math.max(object.size.x, object.size.y, object.size.z) * 2.4,
    );
    camera.position.copy(
      target.clone().add(new THREE.Vector3(distance, distance * 0.8, distance)),
    );
    const orbit = controls as unknown as {
      target?: THREE.Vector3;
      update?: () => void;
    };
    orbit?.target?.copy(target);
    camera.lookAt(target);
    orbit?.update?.();
  }, [camera, controls, request]);
  return null;
}

function FocusRobot({
  robots,
  id,
  request,
}: {
  robots?: CellRobot[];
  id?: string;
  request?: string;
}) {
  const camera = useThree((s) => s.camera),
    controls = useThree((s) => s.controls);
  const robot = robots?.find((r) => r.instance.instance.id === id);
  useEffect(() => {
    if (!robot) return;
    const base = robot.instance.base_pose ?? { x: 0, y: 0, z: 0, yaw: 0 };
    const target = vector(base).add(new THREE.Vector3(0, 0.2, 0));
    camera.position.copy(target.clone().add(new THREE.Vector3(1.1, 0.9, 1.15)));
    const orbit = controls as unknown as {
      target?: THREE.Vector3;
      update?: () => void;
    };
    orbit?.target?.copy(target);
    camera.lookAt(target);
    orbit?.update?.();
  }, [id, request, camera, controls]);
  return null;
}

export default function Scene({
  model,
  q,
  robots,
  objects,
  frame,
  path,
  showGrid,
  resetKey,
  projectId,
  focus,
  onModelStatus,
  workspaces = [],
  workspaceFocus,
  objectLabels=false,
  onSelectObject,
  appearance='studio',
  visualBounds=[],
  selectedRobot,
  robotFocus,
  onSelectRobot,
  onRobotTransform,
  transformMode = "translate",
  editingDisabled = false,
  selectedPart,
  onSelectPart,
}: {
  selectedRobot?: string;
  objectLabels?:boolean;
  onSelectObject?:(id:string)=>void;
  appearance?:'studio'|'business';
  visualBounds?:WorldObject[];
  robotFocus?: { id: string; request: string };
  onSelectRobot?: (id: string, focus?: boolean) => void;
  onRobotTransform?: (id: string, base: RobotBase) => void;
  transformMode?: "translate" | "rotate";
  editingDisabled?: boolean;
  selectedPart?: string;
  onSelectPart?: (part: string) => void;
  model: Model;
  q: Record<string, number>;
  robots?: CellRobot[];
  objects: WorldObject[];
  frame?: Frame | null;
  path: Frame[];
  showGrid: boolean;
  resetKey: number;
  projectId?: string;
  focus?: { id: string; request: string };
  workspaces?: Envelope[];
  workspaceFocus?: string;
  onModelStatus?: (id: string, status: "loading" | "loaded" | "error") => void;
}) {
  const trajectory = useMemo(
    () =>
      (model.planning_supported === false ||
      model.kinematics.solver !== "analytic_yaw_two_link_v1"
        ? []
        : path
      )
        .filter((_, i) => i % 4 === 0)
        .map((f) => {
          const c = f.positions,
            {
              base_height: h,
              upper_arm: a,
              forearm: b,
            } = model.kinematics.links;
          const r =
            a * Math.cos(c.shoulder) + b * Math.cos(c.shoulder + c.elbow);
          const base = robots?.[0]?.instance.base_pose ?? {
            x: 0,
            y: 0,
            z: 0,
            yaw: 0,
          };
          return vector({
            x: base.x + r * Math.cos(c.base_yaw + base.yaw),
            y: base.y + r * Math.sin(c.base_yaw + base.yaw),
            z:
              base.z +
              h +
              a * Math.sin(c.shoulder) +
              b * Math.sin(c.shoulder + c.elbow),
          });
        }),
    [path, model],
  );
  return (
    <SceneBoundary>
      <Canvas
        key={resetKey}
        shadows={{ type: THREE.PCFShadowMap }}
        camera={{
          position:
            robots && robots.length > 1 ? [1.7, 1.45, 1.2] : [1.15, 0.92, 1.12],
          fov: 37,
          near: 0.01,
          far: 200,
        }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <color attach="background" args={[appearance==='business'?'#edf3ef':"#0b0f16"]} />
        {appearance!=='business' && !workspaces.length && (
          <fog
            attach="fog"
            args={[
              "#0b0f16",
              Math.max(
                2.8,
                Math.max(
                  ...objects
                    .filter((o) => o.id === focus?.id)
                    .map((o) => Math.max(o.size.x, o.size.y, o.size.z) * 5),
                  0,
                ),
              ),
              Math.max(
                6,
                Math.max(
                  ...objects
                    .filter((o) => o.id === focus?.id)
                    .map((o) => Math.max(o.size.x, o.size.y, o.size.z) * 12),
                  0,
                ),
              ),
            ]}
          />
        )}
        <ambientLight intensity={1.15} />
        <hemisphereLight args={["#dce8ff", "#26334c", 1.5]} />
        <directionalLight
          position={[1, 2, 1]}
          intensity={3}
          castShadow
          shadow-mapSize={[2048, 2048]}
          shadow-camera-left={-1}
          shadow-camera-right={1}
          shadow-camera-top={1}
          shadow-camera-bottom={-1}
          shadow-normalBias={0.02}
        />
        <mesh
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, -0.006, 0]}
          receiveShadow
        >
          <planeGeometry args={[200, 200]} />
          <meshStandardMaterial color={appearance==='business'?'#dfe9e2':"#111722"} roughness={0.9} />
        </mesh>
        {showGrid && (
          <Grid
            position={[0, 0.001, 0]}
            args={[3, 3]}
            cellSize={0.1}
            cellThickness={0.5}
            cellColor={appearance==='business'?'#b2c7bc':"#263142"}
            sectionSize={0.5}
            sectionThickness={1}
            sectionColor={appearance==='business'?'#95b1a3':"#3b4b64"}
            fadeDistance={3}
            fadeStrength={1.6}
            infiniteGrid
          />
        )}
        <Suspense fallback={null}>
          <ContactShadows
            position={[0, 0.002, 0]}
            opacity={0.4}
            scale={2.5}
            blur={2}
            far={1}
          />
        </Suspense>
        {robots?.length ? (
          robots.map((r) => (
            <EditableRobot
              key={r.instance.instance.id}
              robot={r}
              q={
                frame?.robot_positions?.[r.instance.instance.id] ??
                r.state.positions
              }
              selected={selectedRobot === r.instance.instance.id}
              mode={transformMode}
              disabled={editingDisabled}
                showLabel={objectLabels}
              onSelect={
                onSelectRobot
                  ? (focus) => onSelectRobot(r.instance.instance.id, focus)
                  : undefined
              }
              onTransform={
                onRobotTransform
                  ? (base) => onRobotTransform(r.instance.instance.id, base)
                  : undefined
              }
            />
          ))
        ) : (
          <Robot
            model={model}
            q={q}
            selectedPart={selectedPart}
            onSelectPart={onSelectPart}
          />
        )}
        {objects.map((o) => {
          const displayed = {
            ...o,
            position: frame?.objects[o.id] ?? o.position,
          };
          return (
            <group key={o.id} name={`world-object-${o.id}`} onClick={onSelectObject?e=>{e.stopPropagation();onSelectObject(o.id);}:undefined}>
              {objectLabels&&<RobotLabel position={vector({...displayed.position,z:displayed.position.z+o.size.z/2+.035})}><button className="scene-asset-label" aria-label={`Asset ${o.name}`} onClick={()=>onSelectObject?.(o.id)}>{o.name}</button></RobotLabel>}
              {o.mesh ? (
                <group position={vector(displayed.position)}>
                  <ImportedObject
                    object={displayed}
                    projectId={projectId}
                    onStatus={onModelStatus}
                  />
                </group>
              ) : o.kind === "region" ? (
                <Basket object={displayed} />
              ) : o.kind === "object" &&
                (o.id === "apple" || o.id.startsWith("apple_")) ? (
                <group
                  position={vector(displayed.position)}
                  scale={[o.size.x / 0.065, o.size.z / 0.065, o.size.y / 0.065]}
                >
                  <Apple position={new THREE.Vector3()} />
                </group>
              ) : (
                <mesh
                  position={vector(displayed.position)}
                  castShadow
                  receiveShadow
                >
                  <boxGeometry args={[o.size.x, o.size.z, o.size.y]} />
                  <meshStandardMaterial
                    color={o.kind === "obstacle" ? "#b88053" : "#9eaf83"}
                    roughness={0.55}
                  />
                </mesh>
              )}
            </group>
          );
        })}
        {visualBounds.map(o=><group key={'visual-'+o.id} position={vector(o.position)}><mesh><boxGeometry args={[o.size.x,o.size.z,o.size.y]}/><meshBasicMaterial color="#477b6a" wireframe transparent opacity={.3}/></mesh>{objectLabels&&<RobotLabel position={[0,o.size.z/2+.04,0]}><button className="scene-asset-label" onClick={()=>onSelectObject?.(o.id)}>{o.name}</button></RobotLabel>}</group>)}
        {trajectory.length > 1 && (
          <Line
            points={trajectory}
            color="#bdce86"
            lineWidth={1.2}
            dashed
            dashSize={0.012}
            gapSize={0.009}
            transparent
            opacity={0.45}
          />
        )}
        <Line
          points={[
            [0, 0.005, 0],
            [0.13, 0.005, 0],
          ]}
          color="#c87064"
          lineWidth={2}
        />
        <Line
          points={[
            [0, 0.005, 0],
            [0, 0.005, -0.13],
          ]}
          color="#85ad72"
          lineWidth={2}
        />
        <Line
          points={[
            [0, 0.005, 0],
            [0, 0.13, 0],
          ]}
          color="#6a9fc5"
          lineWidth={2}
        />
        <OrbitControls
          makeDefault
          target={
            robots && robots.length > 1
              ? [0.15, 0.18, -0.65]
              : [0.15, 0.18, -0.03]
          }
          minDistance={0.12}
          maxDistance={50}
          maxPolarAngle={Math.PI / 2 - 0.025}
        />
        <WorkspaceOverlay
          workspaces={workspaces}
          focusRequest={workspaceFocus}
        />
        <FocusRobot
          robots={robots}
          id={robotFocus?.id}
          request={robotFocus?.request}
        />
        <FocusObject
          object={[...objects,...visualBounds].find((o) => o.id === focus?.id)}
          request={focus?.request}
        />
      </Canvas>
    </SceneBoundary>
  );
}

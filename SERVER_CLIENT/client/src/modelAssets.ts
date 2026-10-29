import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import type { ModelAsset, Pose } from "./types";
export const MAX_MODEL_BYTES = 25 * 1024 * 1024;
export type ModelFormat = ModelAsset["format"];

export function modelFormat(filename: string): ModelFormat {
  const value = filename.split(".").at(-1)?.toLowerCase();
  if (!["glb", "gltf", "obj", "stl"].includes(value ?? ""))
    throw new Error("Choose a GLB, embedded glTF, OBJ or STL model.");
  return value as ModelFormat;
}

function validateGLTF(data: ArrayBuffer, format: ModelFormat) {
  let text: string;
  if (format === "glb") {
    if (data.byteLength < 20) throw new Error("Invalid GLB file.");
    const view = new DataView(data);
    const length = view.getUint32(12, true);
    if (
      view.getUint32(0, true) !== 0x46546c67 ||
      view.getUint32(4, true) !== 2 ||
      view.getUint32(8, true) !== data.byteLength ||
      view.getUint32(16, true) !== 0x4e4f534a ||
      20 + length > data.byteLength
    )
      throw new Error("Import a valid GLB 2.0 file.");
    text = new TextDecoder().decode(new Uint8Array(data, 20, length));
  } else text = new TextDecoder().decode(data);
  const document = JSON.parse(text);
  if (document.asset?.version !== "2.0")
    throw new Error("Import a glTF 2.0 model.");
  const visit = (value: unknown) => {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object")
      for (const [key, child] of Object.entries(value)) {
        if (
          key === "uri" &&
          (typeof child !== "string" ||
            !/^data:(application\/(octet-stream|gltf-buffer)|image\/(png|jpeg|webp));base64,/.test(
              child,
            ))
        )
          throw new Error(
            "Use a self-contained GLB or glTF with embedded buffers and textures. External files and URLs are not loaded.",
          );
        visit(child);
      }
  };
  visit(document);
  if (
    document.extensionsRequired?.some((e: string) =>
      [
        "KHR_draco_mesh_compression",
        "EXT_meshopt_compression",
        "KHR_texture_basisu",
      ].includes(e),
    )
  )
    throw new Error(
      "Export an uncompressed model with PNG/JPEG/WebP textures before importing.",
    );
}

export async function parseModel(
  data: ArrayBuffer,
  format: ModelFormat,
  upAxis: "Y" | "Z",
) {
  if (!data.byteLength || data.byteLength > MAX_MODEL_BYTES)
    throw new Error("Model files must be nonempty and at most 25 MB.");
  let source: THREE.Object3D;
  if (format === "glb" || format === "gltf") {
    validateGLTF(data, format);
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((url) => {
      if (!url.startsWith("data:") && !url.startsWith("blob:"))
        throw new Error("External model resources are not loaded.");
      return url;
    });
    source = (await new GLTFLoader(manager).parseAsync(data, "")).scene;
  } else if (format === "obj")
    source = new OBJLoader().parse(new TextDecoder().decode(data));
  else
    source = new THREE.Mesh(
      new STLLoader().parse(data),
      new THREE.MeshStandardMaterial({
        color: "#b8c8a5",
        roughness: 0.65,
        metalness: 0.1,
      }),
    );
  let vertices = 0;
  const remove: THREE.Object3D[] = [];
  try {
    source.traverse((node) => {
      if (node instanceof THREE.Light || node instanceof THREE.Camera)
        remove.push(node);
      const geometry = (node as THREE.Mesh).geometry;
      if (geometry) {
        const positions = geometry.getAttribute("position");
        if (positions) {
          vertices +=
            positions.count *
            ((node as THREE.InstancedMesh).isInstancedMesh
              ? (node as THREE.InstancedMesh).count
              : 1);
          if (vertices > 1000000)
            throw new Error(
              "This model exceeds the one-million-vertex import limit. Export a simpler mesh.",
            );
          for (let i = 0; i < positions.count; i++)
            if (
              ![positions.getX(i), positions.getY(i), positions.getZ(i)].every(
                Number.isFinite,
              )
            )
              throw new Error("Model contains invalid vertex coordinates.");
        }
        node.castShadow = true;
        node.receiveShadow = true;
      }
    });
    remove.forEach((node) => node.removeFromParent());
    if (!vertices)
      throw new Error("The model has no renderable mesh geometry.");
    const oriented = new THREE.Group();
    oriented.add(source);
    if (upAxis === "Z") oriented.rotation.x = -Math.PI / 2;
    oriented.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(oriented, true);
    const extent = bounds.getSize(new THREE.Vector3());
    if (
      ![extent.x, extent.y, extent.z].every(Number.isFinite) ||
      Math.max(extent.x, extent.y, extent.z) < 1e-9
    )
      throw new Error("The model has invalid or empty bounds.");
    const center = bounds.getCenter(new THREE.Vector3());
    oriented.position.sub(center);
    const scene = new THREE.Group();
    scene.add(oriented);
    scene.scale.set(
      extent.x > 1e-9 ? 1 / extent.x : 1,
      extent.y > 1e-9 ? 1 / extent.y : 1,
      extent.z > 1e-9 ? 1 / extent.z : 1,
    );
    const size: Pose = { x: extent.x, y: extent.z, z: extent.y };
    return { scene, size };
  } catch (error) {
    disposeModel(source);
    throw error;
  }
}

export function disposeModel(source: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>(),
    materials = new Set<THREE.Material>(),
    textures = new Set<THREE.Texture>();
  source.traverse((node) => {
    const mesh = node as THREE.Mesh;
    if (mesh.geometry) geometries.add(mesh.geometry);
    if (mesh.material)
      for (const material of Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material])
        materials.add(material);
  });
  materials.forEach((material) =>
    Object.values(material).forEach((value) => {
      if (value instanceof THREE.Texture) textures.add(value);
    }),
  );
  textures.forEach((texture) => {
    const image = texture.image as { close?: () => void } | undefined;
    image?.close?.();
    texture.dispose();
  });
  materials.forEach((material) => material.dispose());
  geometries.forEach((geometry) => geometry.dispose());
}

export function assetURL(projectId: string, assetId: string) {
  return `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}`;
}

// A tetrahedron with a nonzero bounding box, encoded in each supported format.
const positions = new Float32Array([
  -1, -1, -1, 1, -1, -1, 0, 1, -1, -1, -1, -1, 0, 0, 1, 1, -1, -1, 1, -1, -1, 0,
  0, 1, 0, 1, -1, 0, 1, -1, 0, 0, 1, -1, -1, -1,
]);
export const obj = Buffer.from(
  "v -1 -1 -1\nv 1 -1 -1\nv 0 1 -1\nv 0 0 1\nf 1 2 3\nf 1 4 2\nf 2 4 3\nf 3 4 1\n",
);
export const stl = Buffer.from(
  "solid test\n" +
    Array.from(
      { length: 4 },
      (_, n) =>
        "facet normal 0 0 1\nouter loop\n" +
        [0, 1, 2]
          .map(
            (i) =>
              `vertex ${positions[n * 9 + i * 3]} ${positions[n * 9 + i * 3 + 1]} ${positions[n * 9 + i * 3 + 2]}\n`,
          )
          .join("") +
        "endloop\nendfacet\n",
    ).join("") +
    "endsolid test\n",
);
function document(uri?: string) {
  return {
    asset: { version: "2.0" },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 }, material: 0 }] }],
    images: [
      {
        uri: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=",
      },
    ],
    textures: [{ source: 0 }],
    materials: [
      {
        pbrMetallicRoughness: {
          baseColorFactor: [0.2, 0.8, 0.5, 1],
          baseColorTexture: { index: 0 },
          metallicFactor: 0,
          roughnessFactor: 0.7,
        },
      },
    ],
    buffers: [{ byteLength: positions.byteLength, ...(uri ? { uri } : {}) }],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: positions.byteLength },
    ],
    accessors: [
      {
        bufferView: 0,
        componentType: 5126,
        count: 12,
        type: "VEC3",
        min: [-1, -1, -1],
        max: [1, 1, 1],
      },
    ],
  };
}
const binary = Buffer.from(positions.buffer);
export const gltf = Buffer.from(
  JSON.stringify(
    document(
      "data:application/octet-stream;base64," + binary.toString("base64"),
    ),
  ),
);
const json = Buffer.from(JSON.stringify(document()));
const jsonPadded = Buffer.concat([
  json,
  Buffer.alloc((4 - (json.length % 4)) % 4, 32),
]);
const head = Buffer.alloc(20);
head.write("glTF");
head.writeUInt32LE(2, 4);
head.writeUInt32LE(28 + jsonPadded.length + binary.length, 8);
head.writeUInt32LE(jsonPadded.length, 12);
head.writeUInt32LE(0x4e4f534a, 16);
const binHeader = Buffer.alloc(8);
binHeader.writeUInt32LE(binary.length);
binHeader.writeUInt32LE(0x004e4942, 4);
export const glb = Buffer.concat([head, jsonPadded, binHeader, binary]);

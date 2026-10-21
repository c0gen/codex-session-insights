import {
  Group,
  Mesh,
  MeshStandardMaterial,
  BoxGeometry,
  Box3,
  Vector3,
  Matrix4,
  Quaternion,
  CylinderGeometry,
  InstancedMesh,
  Line,
  LineSegments,
  BufferGeometry,
  Float32BufferAttribute,
  LineBasicMaterial,
  SphereGeometry,
} from "three";
import type { SceneLabel, WorldScene } from "../types";

export function block(
  root: Group,
  size: [number, number, number],
  position: [number, number, number],
  color = 0xece7d9,
) {
  const mesh = new Mesh(
    new BoxGeometry(...size),
    new MeshStandardMaterial({ color, roughness: 0.75 }),
  );
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  root.add(mesh);
  return mesh;
}
export function matrix(
  x: number,
  y: number,
  z: number,
  scale = 1,
  fill = 1,
  rotation = 0,
) {
  return new Matrix4().compose(
    new Vector3(x, y, z),
    new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), rotation),
    new Vector3(scale * fill, scale, scale),
  );
}
export function label(
  text: string,
  x: number,
  y: number,
  z = 0,
  priority = 0,
): SceneLabel {
  return { text, position: new Vector3(x, y, z), priority };
}
export function lines(root: Group, points: number[], color = 0x9cacae) {
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(points, 3));
  const line = new LineSegments(
    geometry,
    new LineBasicMaterial({ color, transparent: true, opacity: 0.65 }),
  );
  root.add(line);
  return line;
}
export function globe(root: Group, radius = 1, x = 0, y = 1) {
  const sphere = new Mesh(
    new SphereGeometry(radius, 48, 32),
    new MeshStandardMaterial({ color: 0x406779, roughness: 0.8 }),
  );
  sphere.position.set(x, y, 0);
  root.add(sphere);
  const wire = new Mesh(
    new SphereGeometry(radius * 1.003, 24, 12),
    new MeshStandardMaterial({
      color: 0x8cb1b4,
      wireframe: true,
      transparent: true,
      opacity: 0.16,
    }),
  );
  wire.position.copy(sphere.position);
  root.add(wire);
  return sphere;
}
export function finish(
  root: Group,
  labels: SceneLabel[],
  note: string,
  anchors: Record<string, [number, number, number]> = {},
  fixedBounds?: Box3,
): WorldScene {
  root.updateMatrixWorld(true);
  let bounds = fixedBounds?.clone() ?? new Box3().setFromObject(root);
  if (bounds.isEmpty())
    bounds = new Box3(new Vector3(-0.5, 0, -0.5), new Vector3(0.5, 1, 0.5));
  const size = bounds.getSize(new Vector3()),
    extent = Math.max(size.x, size.y, size.z, 0.1);
  const thickness = Math.min(extent * 0.005, 0.03);
  const floor = new Mesh(
    new CylinderGeometry(extent * 0.8, extent * 0.8, thickness, 48),
    new MeshStandardMaterial({ color: 0xe3e5e1, roughness: 0.94 }),
  );
  floor.position.set(
    bounds.getCenter(new Vector3()).x,
    -thickness,
    bounds.getCenter(new Vector3()).z,
  );
  floor.receiveShadow = true;
  root.add(floor);
  const presets: WorldScene["presets"] = {
    fit: { bounds: bounds.clone(), direction: [1, 0.65, 1.5] },
  };
  for (const [key, anchor] of Object.entries(anchors)) {
    const target = new Vector3(...anchor);
    presets[key] = {
      bounds: new Box3().setFromCenterAndSize(
        target,
        new Vector3(1, 0.6, 0.8).multiplyScalar(extent * 0.3),
      ),
      direction: [0.6, 0.4, 1],
    };
  }
  return {
    root,
    labels,
    bounds,
    presets,
    note,
    dispose() {
      root.traverse((o) => {
        if (o instanceof InstancedMesh) o.dispose();
        if ((o instanceof Mesh || o instanceof Line) && !o.userData.shared) {
          o.geometry.dispose();
          (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) =>
            m.dispose(),
          );
        }
      });
      root.clear();
    },
  };
}

/** Releases only scene-owned resources; imported prototypes belong to AssetLibrary. */
export function clearGroup(root: Group) {
  root.traverse((o) => {
    if (o instanceof InstancedMesh) o.dispose();
    if ((o instanceof Mesh || o instanceof Line) && !o.userData.shared) {
      o.geometry.dispose();
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) =>
        m.dispose(),
      );
    }
  });
  root.clear();
}

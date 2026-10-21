import { Box3, Vector3, PerspectiveCamera, OrthographicCamera } from "three";
import type { CameraPreset } from "./types";

export type ExhibitCamera = PerspectiveCamera | OrthographicCamera;
export interface CameraState {
  position: number[];
  target: number[];
  projection: "perspective" | "orthographic";
  span: number;
  fov?: number;
  selected?: number;
}
export function corners(bounds: Box3) {
  const out: Vector3[] = [];
  for (const x of [bounds.min.x, bounds.max.x])
    for (const y of [bounds.min.y, bounds.max.y])
      for (const z of [bounds.min.z, bounds.max.z])
        out.push(new Vector3(x, y, z));
  return out;
}
export function resizeCamera(
  camera: ExhibitCamera,
  aspect: number,
  span: number,
) {
  if (camera instanceof PerspectiveCamera) camera.aspect = aspect;
  else
    Object.assign(camera, {
      left: (-span * aspect) / 2,
      right: (span * aspect) / 2,
      top: span / 2,
      bottom: -span / 2,
    });
  camera.updateProjectionMatrix();
}
export function fitCamera(
  camera: ExhibitCamera,
  preset: CameraPreset,
  aspect: number,
) {
  camera.zoom = 1;
  if (camera instanceof PerspectiveCamera) camera.fov = preset.fov ?? 38;
  const center = preset.bounds.getCenter(new Vector3());
  if (preset.position && preset.target) {
    camera.position.set(...preset.position);
    center.set(...preset.target);
    camera.lookAt(center);
    resizeCamera(camera, aspect, 4);
    camera.updateMatrixWorld();
    return { target: center, span: 4 };
  }
  const direction = new Vector3(
    ...(preset.direction ?? [1, 0.65, 1.5]),
  ).normalize();
  const right = new Vector3()
    .crossVectors(new Vector3(0, 1, 0), direction)
    .normalize();
  const up = new Vector3().crossVectors(direction, right).normalize();
  const tan = Math.tan(((preset.fov ?? 38) * Math.PI) / 360);
  let distance = 0,
    halfHeight = 0;
  for (const p of corners(preset.bounds)) {
    p.sub(center);
    const x = Math.abs(p.dot(right)),
      y = Math.abs(p.dot(up)),
      z = p.dot(direction);
    halfHeight = Math.max(halfHeight, y, x / aspect);
    distance = Math.max(distance, z + Math.max(y / tan, x / (tan * aspect)));
  }
  const extent = Math.max(
    preset.bounds.getSize(new Vector3()).length(),
    0.0001,
  );
  const span = Math.max(halfHeight * 2.65, extent * 0.08);
  camera.position
    .copy(center)
    .addScaledVector(direction, Math.max(distance * 1.3, extent * 0.4));
  camera.near = Math.max(0.0000001, extent / 100000);
  camera.far = Math.max(1000, extent * 100);
  camera.lookAt(center);
  resizeCamera(camera, aspect, span);
  camera.updateMatrixWorld();
  return { target: center, span };
}

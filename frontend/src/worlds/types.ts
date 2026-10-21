import type { Group, Vector3, Box3, Camera } from "three";
import type { AssetLibrary } from "./assets";
import type { WorldSnapshot, WorldOptions } from "./data";
export interface AssetMetadata {
  id: string;
  file: string;
  sizeM: number[];
  boundsM: number[][];
  triangles: number;
  bytes: number;
  sha256: string;
  artifactId: string;
  sourceRevision: string;
  units: string;
  up: string;
  origin: string;
  anchors: Record<string, number[]>;
}
export interface SceneLabel {
  id?: string;
  text: string;
  position: Vector3;
  priority?: number;
  placement?: "side" | "above";
  required?: boolean;
  leader?: boolean;
}
export interface ViewFrame {
  camera: Camera;
  target: Vector3;
  width: number;
  height: number;
}
export interface CameraPreset {
  bounds: Box3;
  direction?: [number, number, number];
  projection?: "perspective" | "orthographic";
  position?: [number, number, number];
  target?: [number, number, number];
  fov?: number;
}
export interface Inspection {
  count: number;
  selected: number;
  noun: string;
  description: string;
  summary: string;
  map: {
    x: number;
    z: number;
    width: number;
    depth: number;
    cells: {
      x: number;
      z: number;
      width: number;
      depth: number;
      index: number;
      count: number;
    }[];
  };
}
export interface WorldScene {
  root: Group;
  labels: SceneLabel[];
  bounds: Box3;
  presets: Record<string, CameraPreset>;
  initialPreset?: string;
  protectedBounds?: Box3[];
  updateView?(view: ViewFrame): void;
  select?(index: number): void;
  inspection?(): Inspection;
  selectedBounds?(): Box3;
  overviewSvg?(): string;
  note: string;
  dispose(): void;
}
export type SceneFactory = (
  snapshot: WorldSnapshot,
  options: WorldOptions,
  assets: AssetLibrary,
) => WorldScene;

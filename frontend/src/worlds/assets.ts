import {
  Group,
  Mesh,
  Matrix4,
  InstancedMesh,
  type Material,
  type BufferGeometry,
} from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import manifest from "./assets/manifest.json";
import type { AssetMetadata } from "./types";

export const ASSET_CATALOG: readonly AssetMetadata[] = manifest.assets;

// Eager imports embed bytes in the single-file report; parsing remains on demand.
const embedded = import.meta.glob("./assets/*.glb", {
  eager: true,
  query: "?url&inline",
  import: "default",
}) as Record<string, string>;

export class AssetLibrary {
  private loaded = new Map<string, Promise<Group>>();
  private groups = new Set<Group>();
  private closed = false;
  async load(ids: string[]) {
    await Promise.all([...new Set(ids)].map((id) => this.get(id)));
  }
  get(id: string): Promise<Group> {
    if (this.closed) return Promise.reject(new Error("Asset library closed"));
    let promise = this.loaded.get(id);
    if (!promise) {
      promise = this.decode(id);
      this.loaded.set(id, promise);
    }
    return promise;
  }
  private async decode(id: string) {
    const metadata = ASSET_CATALOG.find((a) => a.id === id);
    if (!metadata) throw new Error(`Unknown model: ${id}`);
    const url = embedded[`./assets/${id}.glb`];
    if (!url?.startsWith("data:"))
      throw new Error(`Embedded model unavailable: ${id}`);
    const bytes = Uint8Array.from(atob(url.split(",")[1]), (c) =>
      c.charCodeAt(0),
    );
    if (bytes.byteLength !== metadata.bytes)
      throw new Error(`Incomplete model: ${id}`);
    const gltf = await new GLTFLoader().parseAsync(bytes.buffer, "");
    gltf.scene.updateMatrixWorld(true);
    const byMaterial = new Map<Material, BufferGeometry[]>();
    gltf.scene.traverse((object) => {
      if (!(object instanceof Mesh)) return;
      const material = Array.isArray(object.material)
        ? object.material[0]
        : object.material;
      const geometries = byMaterial.get(material) || [];
      geometries.push(object.geometry.clone().applyMatrix4(object.matrixWorld));
      byMaterial.set(material, geometries);
    });
    const result = new Group();
    result.name = id;
    for (const [material, geometries] of byMaterial) {
      const geometry = mergeGeometries(geometries);
      geometries.forEach((g) => g.dispose());
      if (!geometry) throw new Error(`Could not assemble ${id}`);
      const mesh = new Mesh(geometry, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.shared = true;
      result.add(mesh);
    }
    gltf.scene.traverse((o) => {
      if (o instanceof Mesh) o.geometry.dispose();
    });
    if (this.closed) {
      this.release(result);
      throw new Error("Asset library closed");
    }
    this.groups.add(result);
    return result;
  }
  /** Only called after load() resolves for the scene's declared assets. */
  model(id: string, scale = 1): Group {
    const source = [...this.groups].find((g) => g.name === id);
    if (!source) throw new Error(`Model not loaded: ${id}`);
    const result = source.clone();
    result.scale.setScalar(scale);
    return result;
  }
  instances(id: string, matrices: Matrix4[]): Group {
    const source = [...this.groups].find((g) => g.name === id);
    if (!source) throw new Error(`Model not loaded: ${id}`);
    const group = new Group();
    source.children.forEach((child) => {
      const mesh = child as Mesh;
      const instance = new InstancedMesh(
        mesh.geometry,
        mesh.material,
        matrices.length,
      );
      matrices.forEach((matrix, i) => instance.setMatrixAt(i, matrix));
      instance.userData.shared = true;
      instance.castShadow = true;
      instance.receiveShadow = true;
      instance.computeBoundingSphere();
      group.add(instance);
    });
    return group;
  }
  private release(group: Group) {
    group.traverse((object) => {
      if (object instanceof Mesh) {
        object.geometry.dispose();
        (Array.isArray(object.material)
          ? object.material
          : [object.material]
        ).forEach((m) => m.dispose());
      }
    });
  }
  dispose() {
    this.closed = true;
    this.groups.forEach((g) => this.release(g));
    this.groups.clear();
    this.loaded.clear();
  }
}

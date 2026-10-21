import {
  Scene,
  PerspectiveCamera,
  OrthographicCamera,
  WebGLRenderer,
  HemisphereLight,
  DirectionalLight,
  Color,
  Vector3,
  Spherical,
  SRGBColorSpace,
  ACESFilmicToneMapping,
  PCFSoftShadowMap,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { AssetLibrary } from "./assets";
import { factories, requiredAssets } from "./scenes";
import type { WorldScene } from "./types";
import type { WorldId, WorldSnapshot, WorldOptions } from "./data";
import { trailMode } from "./data";
import {
  fitCamera,
  resizeCamera,
  type ExhibitCamera,
  type CameraState,
} from "./camera";
import {
  layoutAnnotations,
  drawAnnotations,
  LABEL_FONT,
  type Annotation,
} from "./annotations";

export type { CameraState } from "./camera";
export type CameraMemory = Partial<Record<WorldId, CameraState>>;
export interface ProjectedLabel {
  text: string;
  x: number;
  y: number;
}

/** A single, on-demand graphics context. All asynchronous work is generation-guarded. */
export class WorldRenderer {
  private scene = new Scene();
  private camera: ExhibitCamera = new PerspectiveCamera(38, 1, 0.000001, 10000);
  private span = 4;
  private viewKey = "";
  private gl: WebGLRenderer;
  private controls: OrbitControls;
  private assets = new AssetLibrary();
  private world: WorldScene | null = null;
  private id: WorldId | null = null;
  private frame = 0;
  private generation = 0;
  private disposed = false;
  private visible = true;
  private resize: ResizeObserver;
  private intersection: IntersectionObserver;
  private events = new AbortController();
  private labelLayer = document.createElement("div");
  private presented: Annotation[] = [];
  private rail = document.createElement("div");
  private measure = document.createElement("canvas").getContext("2d")!;

  constructor(
    private host: HTMLElement,
    private memory: CameraMemory,
    private changed: (note: string) => void,
    private failed: () => void,
  ) {
    this.gl = new WebGLRenderer({
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: false,
      powerPreference: "low-power",
    });
    this.gl.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.gl.outputColorSpace = SRGBColorSpace;
    this.gl.toneMapping = ACESFilmicToneMapping;
    this.gl.toneMappingExposure = 1;
    this.gl.shadowMap.enabled = true;
    this.gl.shadowMap.type = PCFSoftShadowMap;
    this.scene.background = new Color(0xf0f1ec);
    this.scene.add(new HemisphereLight(0xffffff, 0xa6a89b, 1.8));
    const key = new DirectionalLight(0xfff2d8, 2.6);
    key.position.set(4, 7, 5);
    this.scene.add(key);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.bias = -0.0003;
    Object.assign(key.shadow.camera, {
      left: -6,
      right: 6,
      top: 6,
      bottom: -6,
      near: 0.1,
      far: 30,
    });
    key.shadow.camera.updateProjectionMatrix();
    const fill = new DirectionalLight(0xd4e5ed, 1.1);
    fill.position.set(-5, 3, -3);
    this.scene.add(fill);
    const canvas = this.gl.domElement;
    canvas.id = "world-canvas";
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "img");
    canvas.setAttribute(
      "aria-label",
      "Interactive 3D exhibit. Drag to orbit, scroll to zoom. Arrow keys orbit, Shift and arrows pan, plus and minus zoom, Home resets.",
    );
    this.labelLayer.className = "world-labels";
    this.labelLayer.setAttribute("aria-hidden", "true");
    this.rail.className = "world-annotation-rail";
    this.rail.setAttribute("aria-hidden", "true");
    host.append(canvas, this.labelLayer, this.rail);
    this.measure.font = LABEL_FONT;
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = false;
    this.controls.minDistance = 0.00001;
    this.controls.maxDistance = 1e8;
    this.controls.addEventListener("change", () => this.request());
    const signal = this.events.signal;
    canvas.addEventListener("keydown", (e) => this.key(e), { signal });
    canvas.addEventListener(
      "webglcontextlost",
      (e) => {
        e.preventDefault();
        if (!this.disposed) this.failed();
      },
      { signal },
    );
    document.addEventListener(
      "visibilitychange",
      () => {
        if (document.hidden) this.cancel();
        else this.request();
      },
      { signal },
    );
    this.resize = new ResizeObserver(() => this.resizeToHost());
    this.resize.observe(host);
    this.intersection = new IntersectionObserver((entries) => {
      this.visible = entries[0]?.isIntersecting ?? true;
      if (this.visible) this.request();
      else this.cancel();
    });
    this.intersection.observe(host);
    this.resizeToHost();
  }

  private resizeToHost() {
    if (this.disposed) return;
    const width = Math.max(1, this.host.clientWidth),
      height = Math.max(1, this.host.clientHeight - 44);
    this.gl.setSize(width, height, false);
    resizeCamera(this.camera, width / height, this.span);
    this.request();
  }
  private remember() {
    if (this.id) this.memory[this.id] = this.cameraState();
  }
  async update(snapshot: WorldSnapshot, options: WorldOptions) {
    const ticket = ++this.generation;
    try {
      await this.assets.load(requiredAssets(snapshot, options));
      if (this.disposed || ticket !== this.generation) return;
      const next = factories[options.world](snapshot, options, this.assets);
      const key =
        options.world +
        (options.world === "trail"
          ? trailMode(snapshot.trailMetres ?? 0, options.trailView)
          : "");
      const same = this.viewKey === key;
      this.remember();
      if (this.world) {
        this.scene.remove(this.world.root);
        this.world.dispose();
      }
      this.world = next;
      this.scene.add(next.root);
      this.id = options.world;
      this.viewKey = key;
      const saved = this.memory[options.world];
      next.select?.(saved?.selected ?? 0);
      if (!same) {
        if (saved && options.world !== "trail") {
          this.projection(saved.projection);
          this.span = saved.span;
          this.camera.zoom = 1;
          if (this.camera instanceof PerspectiveCamera)
            this.camera.fov = saved.fov ?? 38;
          resizeCamera(
            this.camera,
            this.host.clientWidth / Math.max(1, this.host.clientHeight - 44),
            this.span,
          );
          this.camera.position.fromArray(saved.position);
          this.controls.target.fromArray(saved.target);
          this.controls.update();
        } else this.preset(next.initialPreset ?? "fit");
      }
      // A narrower filter can remove the inspected container. Keep valid camera
      // poses untouched; reframe only when their selected container no longer exists.
      const inspection = next.inspection?.();
      if (
        same &&
        inspection &&
        (inspection.count === 0 ||
          (saved?.selected !== undefined &&
            saved.selected !== inspection.selected))
      )
        this.preset(inspection.count ? "inspect" : "fit");
      this.host.dataset.world = options.world;
      this.host.dataset.tokens = String(snapshot.tokens);
      this.host.dataset.ready = "true";
      this.changed(next.note);
      this.request();
    } catch {
      if (!this.disposed && ticket === this.generation) this.failed();
    }
  }
  preset(name: string) {
    if (name === "last" && this.world?.select)
      this.world.select((this.world.inspection?.().count ?? 1) - 1);
    const preset = this.world?.presets[name] ?? this.world?.presets.fit;
    if (!preset) return;
    this.projection(preset.projection ?? "perspective");
    const fitted = fitCamera(
      this.camera,
      preset,
      this.host.clientWidth / Math.max(1, this.host.clientHeight - 44),
    );
    this.span = fitted.span;
    this.controls.target.copy(fitted.target);
    this.controls.update();
    this.request();
    if (this.world) this.changed(this.world.note);
  }
  private projection(kind: CameraState["projection"]) {
    if (this.camera instanceof OrthographicCamera === (kind === "orthographic"))
      return;
    const next =
      kind === "orthographic"
        ? new OrthographicCamera(-1, 1, 1, -1, 0.000001, 1e7)
        : new PerspectiveCamera(38, 1, 0.000001, 1e7);
    next.position.copy(this.camera.position);
    next.quaternion.copy(this.camera.quaternion);
    this.camera = next;
    this.controls.object = next;
  }
  inspection() {
    return this.world?.inspection?.();
  }
  overviewSvg() {
    return this.world?.overviewSvg?.() ?? "";
  }
  select(index: number) {
    this.world?.select?.(index);
    this.preset("inspect");
  }
  zoom(factor: number) {
    if (this.camera instanceof OrthographicCamera) {
      this.camera.zoom /= factor;
      this.camera.updateProjectionMatrix();
      this.request();
      return;
    }
    const offset = this.camera.position
      .clone()
      .sub(this.controls.target)
      .multiplyScalar(factor);
    this.camera.position.copy(this.controls.target).add(offset);
    this.controls.update();
    this.request();
  }
  private key(event: KeyboardEvent) {
    if (event.key === "Home") {
      event.preventDefault();
      this.preset("fit");
      return;
    }
    if (["+", "=", "-", "_"].includes(event.key)) {
      event.preventDefault();
      this.zoom(event.key === "-" || event.key === "_" ? 1.2 : 1 / 1.2);
      return;
    }
    if (!event.key.startsWith("Arrow")) return;
    event.preventDefault();
    const direction =
      event.key === "ArrowLeft" || event.key === "ArrowDown" ? -1 : 1;
    if (event.shiftKey) {
      const distance =
        this.camera.position.distanceTo(this.controls.target) * 0.04;
      const vector = new Vector3()
        .setFromMatrixColumn(
          this.camera.matrix,
          event.key === "ArrowLeft" || event.key === "ArrowRight" ? 0 : 1,
        )
        .multiplyScalar(distance * direction);
      this.camera.position.add(vector);
      this.controls.target.add(vector);
    } else {
      const spherical = new Spherical().setFromVector3(
        this.camera.position.clone().sub(this.controls.target),
      );
      if (event.key === "ArrowLeft" || event.key === "ArrowRight")
        spherical.theta += direction * 0.12;
      else spherical.phi -= direction * 0.1;
      spherical.makeSafe();
      this.camera.position
        .copy(this.controls.target)
        .add(new Vector3().setFromSpherical(spherical));
    }
    this.controls.update();
    this.request();
  }
  private cancel() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
  }
  request() {
    if (this.disposed || this.frame || document.hidden || !this.visible) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.paint();
    });
  }
  private paint() {
    if (this.disposed) return;
    const width = this.host.clientWidth,
      height = Math.max(1, this.host.clientHeight - 44);
    const focusDistance = this.camera.position.distanceTo(this.controls.target);
    this.camera.near = Math.max(1e-8, focusDistance * 0.005);
    this.camera.far = Math.max(
      10,
      focusDistance * 5,
      this.world
        ? this.camera.position.distanceTo(
            this.world.bounds.getCenter(new Vector3()),
          ) +
            this.world.bounds.getSize(new Vector3()).length() * 2
        : 1000,
    );
    this.camera.updateProjectionMatrix();
    this.camera.updateMatrixWorld();
    this.world?.updateView?.({
      camera: this.camera,
      target: this.controls.target,
      width,
      height,
    });
    this.gl.render(this.scene, this.camera);
    this.host.dataset.drawCalls = String(this.gl.info.render.calls);
    this.host.dataset.triangles = String(this.gl.info.render.triangles);
    this.host.dataset.geometries = String(this.gl.info.memory.geometries);
    this.host.dataset.collection = JSON.stringify(
      this.world?.root.userData.collection ?? null,
    );
    const layout = layoutAnnotations(
      this.world?.labels ?? [],
      this.world?.protectedBounds ?? [],
      this.camera,
      width,
      height,
      (text) => this.measure.measureText(text).width,
    );
    this.presented = layout.labels;
    this.host.dataset.annotations = JSON.stringify(layout);
    this.host.dataset.camera = JSON.stringify(this.cameraState());
    this.labelLayer.replaceChildren();
    this.rail.replaceChildren();
    const overlay = document.createElement("canvas");
    overlay.width = width;
    overlay.height = height;
    overlay.className = "world-leaders";
    // Draw leaders only here; text remains real DOM text with measured bounds.
    const context = overlay.getContext("2d")!;
    for (const label of this.presented) {
      if (label.leader && !label.docked) {
        context.beginPath();
        context.moveTo(...label.anchor);
        context.lineTo(
          Math.max(label.x, Math.min(label.x + label.w, label.anchor[0])),
          Math.max(label.y, Math.min(label.y + label.h, label.anchor[1])),
        );
        context.strokeStyle = "#86683e";
        context.stroke();
      }
      const span = document.createElement("span");
      span.textContent = label.lines.join("\n");
      span.dataset.label = label.id;
      span.style.left = `${label.x}px`;
      span.style.top = `${label.docked ? 4 : label.y}px`;
      span.style.width = `${label.w}px`;
      span.style.height = `${label.h}px`;
      (label.docked ? this.rail : this.labelLayer).append(span);
    }
    this.labelLayer.prepend(overlay);
  }
  capture() {
    this.paint();
    const canvas = document.createElement("canvas");
    canvas.width = this.host.clientWidth;
    canvas.height = this.host.clientHeight;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#f0f1ec";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(this.gl.domElement, 0, 44, canvas.width, canvas.height - 44);
    drawAnnotations(
      ctx,
      this.presented.map((l) => (l.docked ? { ...l, y: -40 } : l)),
      0,
      44,
    );
    return { canvas, labels: [] as ProjectedLabel[] };
  }
  cameraState() {
    return {
      position: this.camera.position.toArray(),
      target: this.controls.target.toArray(),
      projection:
        this.camera instanceof OrthographicCamera
          ? ("orthographic" as const)
          : ("perspective" as const),
      span: this.span / this.camera.zoom,
      fov:
        this.camera instanceof PerspectiveCamera ? this.camera.fov : undefined,
      selected: this.world?.inspection?.().selected,
    };
  }
  dispose() {
    if (this.disposed) return;
    this.remember();
    this.disposed = true;
    this.generation++;
    this.cancel();
    this.resize.disconnect();
    this.intersection.disconnect();
    this.events.abort();
    this.controls.dispose();
    this.world?.dispose();
    this.assets.dispose();
    this.gl.dispose();
    this.gl.forceContextLoss();
    this.gl.domElement.remove();
    this.labelLayer.remove();
    this.rail.remove();
    this.scene.clear();
  }
}

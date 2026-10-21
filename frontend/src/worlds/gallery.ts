import "./worlds.css";
import type { Dashboard } from "../types";
import type { EquivalentBasis } from "../text-equivalents-data";
import { esc } from "../ui";
import { copyPng, savePng } from "../image-transport";
import {
  WORLDS,
  worldSnapshot,
  restoreWorldOptions,
  exhibitMeasure,
  number,
  trailMode,
  type WorldOptions,
  type WorldSnapshot,
} from "./data";
import { REFERENCES, paperLayout } from "./references";
import { WorldRenderer, type CameraMemory } from "./renderer";
import { fallbackSvg, fallbackNote } from "./fallback";
import { captureExhibit } from "./capture";
import { inspectionMap } from "./inspection";

export class WorldsGallery {
  private element: HTMLElement | null = null;
  private renderer: WorldRenderer | null = null;
  private memory: CameraMemory = {};
  private options: WorldOptions;
  private snapshot: WorldSnapshot | null = null;
  private basis: EquivalentBasis = "total";
  private signature = "";
  private note = "";
  private graphicsFailed = false;
  private building = false;
  private sharing = false;
  private loading = false;
  private failedImage: {
    blob: Blob;
    filename: string;
    context: string;
  } | null = null;
  private changeBasis: ((basis: EquivalentBasis) => void) | null = null;

  constructor(private notify: (message: string, error?: boolean) => void) {
    let saved = null;
    try {
      saved = localStorage.getItem("insights-worlds");
    } catch {
      /* Storage is optional. */
    }
    this.options = restoreWorldOptions(saved);
    if (window.__INSIGHTS_REPORT__) this.options.world = "paper";
  }
  render() {
    return '<div id="worlds-host"></div>';
  }
  /** Keep the actual DOM/canvas during dashboard redraws, including filter refreshes. */
  detach(keep: boolean) {
    if (keep) this.element?.remove();
    else this.unmount();
  }
  mount(
    data: Dashboard,
    basis: EquivalentBasis,
    onBasis: (basis: EquivalentBasis) => void,
  ) {
    const host = document.getElementById("worlds-host");
    if (!host) return;
    this.changeBasis = onBasis;
    if (!this.element) {
      this.element = document.createElement("section");
      this.element.className = "worlds-gallery";
      this.element.innerHTML = this.markup();
      this.bind();
    }
    host.append(this.element);
    this.update(data, basis);
  }
  private markup() {
    return `<div class="world-intro"><div><span class="world-eyebrow">TOKEN WORLDS</span><h2>A little perspective on a lot of text.</h2><p>Explore the scale of your tokens, one exhibit at a time.</p></div><div class="world-basis" role="group" aria-label="Visualization token basis"><button id="world-basis-total" data-world-basis="total">Total processed</button><button id="world-basis-output" data-world-basis="output">Output only</button></div></div>
    <div class="world-cards" role="group" aria-label="Choose an exhibit">${WORLDS.map((w, i) => `<button id="world-select-${w.id}" data-world="${w.id}" class="world-card"><span class="world-card-top"><span class="world-symbol" aria-hidden="true">${w.symbol}</span><small>0${i + 1}</small></span><strong>${w.title}</strong><span>${w.subtitle}</span></button>`).join("")}</div>
    <section class="world-exhibit panel" aria-labelledby="world-title"><div class="world-exhibit-heading"><div><span class="world-eyebrow" id="world-edition">SCALE EXHIBIT</span><h2 id="world-title"></h2><p id="world-scope"></p></div><div class="world-measure"><strong id="world-value"></strong><span id="world-value-label"></span><small id="world-counter"></small></div></div>
    <div class="world-toolbar"><div class="world-camera-controls" role="group" aria-label="Camera controls"><button id="world-fit" data-preset="fit">Fit exhibit</button><button id="world-ground" data-preset="ground">Ground</button><button id="world-top" data-preset="top">Top</button><button id="world-compare" data-preset="landmark">Compare landmark</button><button id="world-zoom-in" aria-label="Zoom in">+</button><button id="world-zoom-out" aria-label="Zoom out">−</button></div><label>Units <select id="world-units"><option value="imperial">Feet / miles</option><option value="metric">Metres / kilometres</option></select></label><label id="world-proportions-control">Paper <select id="world-proportions"><option value="readable">Readable width</option><option value="true">True proportions</option></select></label><label id="world-reference-control">Reference <select id="world-reference"><option value="auto">Automatic</option>${REFERENCES.map((r) => `<option value="${r.id}">${r.name}</option>`).join("")}</select></label></div>
    <div class="world-stage"><div id="world-viewport" class="world-viewport"></div><div id="world-fallback" class="world-fallback" hidden></div><div id="world-status" class="world-status" role="status"></div><div id="world-paper-inset" class="world-paper-inset"><span class="world-paper-icon" aria-hidden="true"></span><div><strong>One real sheet</strong><span>8.5 × 11 in · 21.59 × 27.94 cm</span><small>0.004 in thick · close-up, independently magnified</small></div></div></div>
    <div class="world-caption"><p id="world-note"></p><button id="world-retry" class="text-button" hidden>Retry 3D</button><span class="world-help">Drag to orbit · scroll to zoom · Shift + drag to pan<br>Keyboard: arrows orbit · Shift + arrows pan · + / − zoom · Home resets</span></div>
    <div class="world-bottom"><details id="world-assumptions"><summary>How this is calculated</summary><p id="world-formula"></p><p>0.75 words per token is an English-text approximation. Total processed includes cached and repeated context; these are volume equivalents, not unique authored text. Output includes reasoning and tool output.</p><p id="world-reference-note"></p></details><div class="world-share"><button id="world-copy" class="button">Copy exhibit</button><button id="world-save" class="button">Save PNG</button></div></div><p id="world-share-feedback" class="world-share-feedback" role="status" hidden></p></section>`;
  }
  private get<T extends HTMLElement = HTMLElement>(id: string) {
    return this.element!.querySelector<T>(`#${id}`)!;
  }
  private bind() {
    const root = this.element!;
    root.querySelectorAll<HTMLButtonElement>("button[data-world]").forEach(
      (b) =>
        (b.onclick = () => {
          this.options.world = b.dataset.world as WorldOptions["world"];
          this.remember();
          this.refresh();
        }),
    );
    const toolbar = this.get("world-fit").parentElement!;
    for (const [name, title] of [
      ["inspect", "Inside an aisle"],
      ["last", "Last book"],
      ["route", "Fit route"],
    ]) {
      const b = document.createElement("button");
      b.id = `world-${name}`;
      b.dataset.preset = name;
      b.textContent = title;
      toolbar.append(b);
    }
    const controls = this.element!.querySelector(".world-toolbar")!;
    controls.insertAdjacentHTML(
      "beforeend",
      '<label id="world-schedule-control">Schedule <select id="world-schedule"><option value="continuous">Continuous</option><option value="30">30 minutes/day</option><option value="60">1 hour/day</option></select></label><label id="world-trail-control">View <select id="world-trail"><option value="auto">Automatic</option><option value="unrolled">Unrolled trail</option><option value="globe">Globe</option></select></label>',
    );
    this.element!.querySelector(".world-stage")!.insertAdjacentHTML(
      "beforeend",
      '<div id="world-overview" class="world-overview" hidden></div>',
    );
    this.element!.querySelector(".world-caption")!.insertAdjacentHTML(
      "afterend",
      '<div id="world-inspection" class="world-inspection" hidden><div id="world-map" class="world-map"></div><div><p id="world-collection-summary"></p><p id="world-selection" aria-live="polite"></p><div class="world-container-controls"><button id="world-previous">Previous</button><label><span id="world-container-noun">Bookcase</span> <input id="world-container" type="number" min="1" step="1" value="1" aria-label="Container number"></label><button id="world-go">Inspect</button><button id="world-next">Next</button></div></div></div>',
    );
    this.get("world-previous").onclick = () =>
      this.renderer?.select((this.renderer.inspection()?.selected ?? 0) - 1);
    this.get("world-next").onclick = () =>
      this.renderer?.select((this.renderer.inspection()?.selected ?? 0) + 1);
    this.get("world-go").onclick = () =>
      this.renderer?.select(
        Number(this.get<HTMLInputElement>("world-container").value) - 1,
      );
    this.get("world-container").onkeydown = (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        this.get("world-go").click();
      }
    };
    this.get("world-map").onclick = (e) => {
      const target = (e.target as Element).closest<SVGElement>(
        "[data-container]",
      );
      if (target) this.renderer?.select(Number(target.dataset.container));
    };
    this.get("world-map").onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        (e.target as SVGElement).dispatchEvent(
          new MouseEvent("click", { bubbles: true }),
        );
      }
    };
    root
      .querySelectorAll<HTMLButtonElement>("[data-world-basis]")
      .forEach(
        (b) =>
          (b.onclick = () =>
            this.changeBasis?.(b.dataset.worldBasis as EquivalentBasis)),
      );
    root
      .querySelectorAll<HTMLButtonElement>("[data-preset]")
      .forEach(
        (b) => (b.onclick = () => this.renderer?.preset(b.dataset.preset!)),
      );
    this.get("world-zoom-in").onclick = () => this.renderer?.zoom(1 / 1.25);
    this.get("world-zoom-out").onclick = () => this.renderer?.zoom(1.25);
    for (const [id, key] of [
      ["world-units", "units"],
      ["world-proportions", "proportions"],
      ["world-reference", "landmark"],
      ["world-schedule", "readingSchedule"],
      ["world-trail", "trailView"],
    ] as const) {
      this.get<HTMLSelectElement>(id).onchange = (e) => {
        (this.options[key] as string) = (e.target as HTMLSelectElement).value;
        this.remember();
        this.refresh();
      };
    }
    this.get("world-retry").onclick = () => {
      this.graphicsFailed = false;
      this.signature = "";
      this.refresh();
    };
    this.get("world-copy").onclick = () => void this.share("copy");
    this.get("world-save").onclick = () => void this.share("save");
  }
  private remember() {
    try {
      localStorage.setItem("insights-worlds", JSON.stringify(this.options));
    } catch {
      /* Optional preferences. */
    }
  }
  update(data: Dashboard, basis: EquivalentBasis) {
    if (!this.element) return;
    this.basis = basis;
    this.snapshot = worldSnapshot(data, basis);
    this.refresh();
  }
  private refresh() {
    if (!this.element || !this.snapshot) return;
    const s = this.snapshot,
      o = this.options,
      m = exhibitMeasure(s, o),
      world = WORLDS.find((w) => w.id === o.world)!;
    this.get("world-title").textContent = world.title;
    this.get("world-value").textContent = m.value;
    this.get("world-value-label").textContent = m.label;
    this.get("world-counter").textContent =
      `${s.tokens === null ? "Unavailable" : number(s.tokens, 0) + " tokens"}${s.partial ? " · partial" : ""}${s.stale ? " · stale" : ""}`;
    this.get("world-scope").textContent = s.detail;
    this.get("world-formula").textContent = m.explanation;
    this.get("world-edition").textContent = s.demo
      ? "DEMO EXHIBIT"
      : s.saved
        ? "SAVED SNAPSHOT"
        : "SCALE EXHIBIT";
    this.element
      .querySelectorAll<HTMLButtonElement>("button[data-world]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.world === o.world)),
      );
    this.element
      .querySelectorAll<HTMLElement>("[data-world-basis]")
      .forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(b.dataset.worldBasis === this.basis),
        ),
      );
    this.get<HTMLSelectElement>("world-units").value = o.units;
    this.get<HTMLSelectElement>("world-proportions").value = o.proportions;
    this.get<HTMLSelectElement>("world-reference").value = o.landmark;
    this.get<HTMLSelectElement>("world-schedule").value = o.readingSchedule;
    this.get<HTMLSelectElement>("world-trail").value = o.trailView;
    this.get("world-schedule-control").hidden = o.world !== "reading";
    this.get("world-trail-control").hidden = o.world !== "trail";
    this.get("world-units").closest("label")!.hidden = o.world === "reading";
    this.get("world-inspect").hidden = this.get("world-last").hidden = ![
      "library",
      "vault",
    ].includes(o.world);
    this.get("world-inspect").textContent =
      o.world === "library" ? "Inside an aisle" : "Inspect case";
    this.get("world-last").textContent =
      o.world === "library" ? "Last book" : "Last disk";
    this.get("world-route").hidden = o.world !== "trail";
    this.get("world-ground").textContent =
      o.world === "reading" ? "Start" : "Ground";
    this.get("world-top").textContent = o.world === "reading" ? "End" : "Top";
    for (const id of [
      "world-proportions-control",
      "world-reference-control",
      "world-paper-inset",
      "world-compare",
    ])
      this.get(id).hidden = o.world !== "paper";
    this.get("world-paper-inset").hidden = !(
      o.world === "paper" ||
      (o.world === "trail" &&
        trailMode(s.trailMetres ?? 0, o.trailView) === "unrolled")
    );
    for (const id of ["world-ground", "world-top"])
      this.get(id).hidden = !["paper", "reading"].includes(o.world);
    this.get("world-fit").textContent = {
      paper: "Fit stack",
      library: "Whole library",
      trail: "Whole view",
      reading: "Whole journey",
      vault: "Whole vault",
    }[o.world];
    const ref = paperLayout(
      s.values?.stack_meters ?? 0,
      o.proportions,
      o.landmark,
    ).reference;
    this.get("world-reference-note").innerHTML =
      o.world === "paper"
        ? `${esc(ref.name)}: ${esc(ref.note)}. Reference placement is illustrative. ${ref.source ? `<a href="${esc(ref.source)}" target="_blank" rel="noreferrer">Dimension source</a>` : ""}`
        : "Physical layouts and grouping are illustrative; the displayed equivalent is calculated from the selected token total.";
    const signature = JSON.stringify([s.tokens, o]);
    if (signature === this.signature) {
      this.refreshInspection();
      this.buttons();
      return;
    }
    this.signature = signature;
    this.failedImage = null;
    this.get("world-share-feedback").hidden = true;
    this.get("world-fallback").innerHTML = fallbackSvg(s, o);
    this.note =
      o.world === "paper"
        ? o.proportions === "true"
          ? "True sheet proportions; highlighted line and independent close-up."
          : "Height to scale; width enlarged for readability."
        : "Static comparison; see the calculation below.";
    this.get("world-note").textContent = this.note;
    if (!s.values) {
      this.renderer?.dispose();
      this.renderer = null;
      this.building = false;
      this.showFallback("Token counters unavailable.");
      return;
    }
    if (this.graphicsFailed) {
      this.showFallback(
        "3D is unavailable. The calculated comparison is shown below.",
      );
      return;
    }
    this.building = true;
    this.buttons();
    this.get("world-status").textContent = "Preparing exhibit…";
    const viewport = this.get("world-viewport");
    viewport.hidden = false;
    viewport.dataset.ready = "false";
    try {
      if (!this.renderer)
        this.renderer = new WorldRenderer(
          viewport,
          this.memory,
          (note) => {
            this.building = false;
            this.note = note;
            this.get("world-note").textContent = note;
            this.get("world-fallback").hidden = true;
            this.get("world-status").textContent = "";
            this.get("world-retry").hidden = true;
            this.refreshInspection();
            this.buttons();
          },
          () => this.failGraphics(),
        );
      void this.renderer.update(s, { ...o });
    } catch {
      this.failGraphics();
    }
  }
  private failGraphics() {
    if (!this.element) return;
    this.renderer?.dispose();
    this.renderer = null;
    this.graphicsFailed = true;
    this.building = false;
    this.showFallback(
      "3D could not be displayed. Your calculated comparison is still available.",
    );
  }
  private showFallback(message: string) {
    this.note = fallbackNote(this.snapshot!, this.options);
    this.get("world-note").textContent = this.note;
    this.get("world-viewport").hidden = true;
    this.get("world-fallback").hidden = false;
    this.get("world-status").textContent = message;
    this.get("world-retry").hidden = !this.snapshot?.values;
    this.get("world-inspection").hidden = true;
    this.get("world-overview").hidden = true;
    this.buttons();
  }
  private refreshInspection() {
    if (!this.element) return;
    const info = this.renderer?.inspection();
    this.get("world-inspection").hidden = !info;
    if (info) {
      const focused = document.activeElement;
      const mapFocus =
        focused && this.get("world-map").contains(focused)
          ? (focused as SVGElement).dataset.container
          : undefined;
      this.get("world-map").innerHTML = inspectionMap(info);
      if (mapFocus !== undefined)
        this.get("world-map")
          .querySelector<SVGElement>(`[data-container="${mapFocus}"]`)
          ?.focus({ preventScroll: true });
      this.get("world-selection").textContent = info.description;
      this.get("world-collection-summary").textContent = info.summary;
      this.get("world-container-noun").textContent = info.noun;
      const input = this.get<HTMLInputElement>("world-container");
      if (document.activeElement !== input)
        input.value = String(info.selected + 1);
      input.max = String(Math.max(1, info.count));
      input.disabled = !info.count;
      this.get<HTMLButtonElement>("world-previous").disabled =
        info.selected <= 0;
      this.get<HTMLButtonElement>("world-next").disabled =
        info.selected >= info.count - 1;
      this.get<HTMLButtonElement>("world-go").disabled = !info.count;
    }
    const overview = this.renderer?.overviewSvg() ?? "";
    this.get("world-overview").innerHTML = overview;
    this.get("world-overview").hidden = !overview;
  }
  setLoading(value: boolean) {
    this.loading = value;
    this.buttons();
  }
  private buttons() {
    if (!this.element) return;
    for (const id of ["world-copy", "world-save"])
      this.get<HTMLButtonElement>(id).disabled =
        this.sharing || this.building || this.loading || !this.snapshot?.values;
    this.element
      .querySelectorAll<HTMLButtonElement>(
        "[data-preset],#world-zoom-in,#world-zoom-out",
      )
      .forEach((b) => (b.disabled = !this.renderer || this.building));
    this.get("world-copy").textContent = this.sharing
      ? "Preparing image…"
      : "Copy exhibit";
  }
  private async share(action: "copy" | "save") {
    if (this.sharing || this.building || this.loading || !this.snapshot?.values)
      return;
    this.sharing = true;
    this.buttons();
    const o = { ...this.options },
      s = this.snapshot,
      filename = `token-worlds-${o.world}.png`;
    const context = JSON.stringify([s, o, this.renderer?.cameraState()]),
      element = this.element;
    const image =
      this.failedImage?.context === context
        ? Promise.resolve(this.failedImage.blob)
        : captureExhibit(s, o, this.note, this.renderer);
    try {
      if (action === "copy") {
        await copyPng(image);
        this.notify("Exhibit image copied");
      } else {
        const result = await savePng(await image, filename);
        if (result !== "cancelled")
          this.notify(
            result === "saved" ? "Exhibit image saved" : "PNG download started",
          );
      }
      this.failedImage = null;
    } catch {
      try {
        const blob = await image;
        if (
          this.element === element &&
          JSON.stringify([
            this.snapshot,
            this.options,
            this.renderer?.cameraState(),
          ]) === context
        )
          this.failedImage = { blob, filename, context };
      } catch {
        /* No image to preserve on render failure. */
      }
      if (this.element) {
        const feedback = this.get("world-share-feedback");
        feedback.hidden = false;
        feedback.textContent = this.failedImage
          ? "Couldn’t copy or save the image. The generated image is ready; try Save PNG."
          : "Couldn’t generate the exhibit image. Please try again.";
      }
    } finally {
      this.sharing = false;
      this.buttons();
    }
  }
  unmount() {
    this.renderer?.dispose();
    this.renderer = null;
    this.element?.remove();
    this.element = null;
    this.snapshot = null;
    this.signature = "";
    this.building = false;
    this.graphicsFailed = false;
  }
}

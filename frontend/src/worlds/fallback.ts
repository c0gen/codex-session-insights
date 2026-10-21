import { esc } from "../ui";
import {
  exhibitMeasure,
  groupedCount,
  number,
  EARTH_CIRCUIT_M,
  trailMode,
  readingElapsed,
  duration,
  type WorldSnapshot,
  type WorldOptions,
} from "./data";
import { paperLayout } from "./references";
import { CollectionLayout, occupancy } from "./collection-layout";

export function fallbackNote(s: WorldSnapshot, o: WorldOptions) {
  if (o.world === "library")
    return "Static floor plan · 150 novels/bookcase; sections preserve the calculated count. Book dimensions and aisle spacing are assumed.";
  if (o.world === "vault")
    return "Static floor plan · 100 disks/case × 20 cases/rack; final disk shows partial capacity.";
  if (o.world !== "paper")
    return "Static distance/time diagram; see the calculation below.";
  if (o.proportions === "true")
    return "True sheet proportions; a one-pixel outline keeps thin paper visible.";
  const p = paperLayout(s.values?.stack_meters ?? 0, o.proportions, o.landmark);
  const width = Math.max(26, Math.min(75, p.width * 235));
  const enlargement = width / ((0.2159 / p.unit) * 235);
  return `Height to scale · paper width enlarged ×${number(enlargement)} in this static view.`;
}

/** Data-backed, dependency-free counterpart for reports and machines without WebGL. */
export function fallbackSvg(s: WorldSnapshot, o: WorldOptions) {
  const measure = exhibitMeasure(s, o);
  let drawing = "",
    caption = "";
  const text = (value: string, x: number, y: number, size = 16) =>
    `<text x="${x}" y="${y}" text-anchor="middle" font-family="Arial,sans-serif" font-size="${size}" fill="#334e57">${esc(value)}</text>`;
  if (s.values && o.world === "paper") {
    const p = paperLayout(s.values.stack_meters, o.proportions, o.landmark),
      h = p.height * 235;
    const w =
      o.proportions === "true"
        ? p.width * 235
        : Math.max(26, Math.min(75, p.width * 235));
    drawing = `<path d="M160 280H640" stroke="#a3b0ad"/><rect x="${265 - w / 2}" y="${280 - h}" width="${w}" height="${h}" fill="#f9f4e6" stroke="#b78c54"/>`;
    if (p.showReference) {
      const rh = (p.reference.height / p.unit) * 235;
      drawing +=
        `<rect x="485" y="${280 - rh}" width="30" height="${rh}" rx="3" fill="#829ca3"/>` +
        text(p.reference.name, 500, 310, 13);
    }
    drawing +=
      `<path d="M${265 - w / 2} ${280 - h}H155" stroke="#a57c3e"/>` +
      text(measure.value, 105, 285 - h, 14);
    caption = fallbackNote(s, o);
  } else if (s.values && o.world === "trail") {
    if (trailMode(s.trailMetres!, o.trailView) === "unrolled") {
      drawing =
        `<rect x="100" y="140" width="600" height="30" fill="#f7f1df" stroke="#b58b4c"/><path d="M100 130V190M700 130V190" stroke="#587a7b"/>` +
        text("Start", 100, 220) +
        text(measure.value, 700, 220) +
        text("Unrolled trail", 400, 100, 23);
      caption =
        "Length diagram · ribbon width enlarged · each sheet is 27.94 cm long.";
    } else {
      const laps = s.trailMetres! / EARTH_CIRCUIT_M,
        part = laps % 1,
        circ = 2 * Math.PI * 100;
      drawing =
        `<circle cx="400" cy="160" r="100" fill="#e1e9e6" stroke="#b4c5c5" stroke-width="14"/><circle cx="400" cy="160" r="100" fill="none" stroke="#ad7b37" stroke-width="14" stroke-dasharray="${part * circ} ${circ}" transform="rotate(-90 400 160)"/>` +
        text(`${number(laps, 3)} circuits`, 400, 168, 23);
      caption = `${number(Math.floor(laps), 0)} complete circuits; gold marks the remainder. ${measure.value} total.`;
    }
  } else if (s.values && (o.world === "library" || o.world === "vault")) {
    const isLibrary = o.world === "library",
      total = isLibrary ? s.values.novels : s.values.floppy_disks;
    const capacity = isLibrary ? 150 : 2000,
      layout = new CollectionLayout(total, capacity),
      map = layout.map();
    const scale = Math.min(
      520 / Math.max(map.width, 1),
      200 / Math.max(map.depth, 1),
    );
    drawing = text(
      `${number(layout.count, 0)} ${isLibrary ? "bookcases" : "racks"}`,
      400,
      44,
      24,
    );
    for (const c of map.cells)
      drawing += `<rect x="${140 + (c.x - map.x) * scale}" y="${72 + (c.z - map.z) * scale}" width="${Math.max(1, c.width * scale)}" height="${Math.max(2, c.depth * scale)}" fill="#668783"><title>${number(c.count, 0)} ${isLibrary ? "bookcases" : "racks"}</title></rect>`;
    const last = occupancy(total),
      container = occupancy(total, isLibrary ? 150 : 100);
    drawing += text(
      `${number(container.full, 0)} full ${isLibrary ? "bookcases" : "cases"}${container.remainder ? ` + ${number(container.remainder)} ${isLibrary ? "novels" : "disks"} in the final case` : ""}`,
      400,
      292,
      15,
    );
    drawing += text(
      last.remainder
        ? `Final ${isLibrary ? "novel" : "disk"}: ${number(last.remainder * 100)}% filled`
        : "All occupied items are full",
      400,
      316,
      13,
    );
    caption = isLibrary
      ? "150 novels/bookcase · floor-plan sections simplify geometry, not quantity."
      : "100 disks/case · 20 cases/rack · storage layout is assumed.";
  } else if (s.values) {
    const total =
      o.world === "library"
        ? s.values.novels
        : o.world === "vault"
          ? s.values.floppy_disks
          : readingElapsed(s.readingMinutes!, o.readingSchedule) / 525960;
    const g = groupedCount(total, 24);
    for (let i = 0; i < g.count; i++) {
      const x = 160 + (i % 12) * 40,
        y = 85 + Math.floor(i / 12) * 100,
        fill = i === g.count - 1 ? g.last : 1;
      drawing += `<rect x="${x}" y="${y}" width="30" height="74" rx="3" fill="#dce4e0"/><rect x="${x}" y="${y + 74 * (1 - fill)}" width="30" height="${74 * fill}" rx="3" fill="#60818a"/>`;
    }
    caption = `Each block represents ${number(g.unit)} ${o.world === "library" ? "novels" : o.world === "vault" ? "disks" : "reading years"}; the final block shows partial fill.`;
    if (o.world === "reading")
      caption = `${measure.value} ${measure.label} · reading time: ${duration(s.readingMinutes!)} continuously.`;
  }
  if (!s.values) drawing = text("Token counters unavailable", 400, 160, 24);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="360" viewBox="0 0 800 360" role="img" aria-label="${esc(measure.value + " " + measure.label)}"><rect width="800" height="360" fill="#f0f1ec"/>${drawing}${text(caption, 400, 342, 13)}</svg>`;
}

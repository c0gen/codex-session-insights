import type { Inspection } from "./types";
import { esc } from "../ui";

export function inspectionMap(info: Inspection) {
  const m = info.map,
    scale = Math.min(200 / Math.max(m.width, 1), 110 / Math.max(m.depth, 1));
  return `<svg viewBox="0 0 220 134" role="group" aria-label="Collection floor plan; select a section to inspect"><rect width="220" height="134" rx="8" fill="#edf0e8"/>${m.cells
    .map((c) => {
      const active =
        info.selected >= c.index && info.selected < c.index + c.count;
      return `<rect x="${10 + (c.x - m.x) * scale}" y="${8 + (c.z - m.z) * scale}" width="${Math.max(2, c.width * scale)}" height="${Math.max(2, c.depth * scale)}" rx="1" fill="${active ? "#ae7c35" : "#7d9790"}" role="button" tabindex="0" aria-label="${esc(info.noun)} ${c.index + 1}${c.count > 1 ? ` through ${Math.min(info.count, c.index + c.count)}` : ""}" data-container="${c.index}"/>`;
    })
    .join(
      "",
    )}<text x="10" y="128" fill="#36545b" font-size="10">Floor plan · gold marks selection</text></svg>`;
}

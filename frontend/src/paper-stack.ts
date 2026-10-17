import { compact } from "./format";
import { esc } from "./ui";
import type { Dashboard } from "./types";
import { equivalentSnapshot, type EquivalentBasis } from "./text-equivalents-data";

/** Short stacks read better in feet; long ones need no more than three significant digits. */
export function stackHeight(meters: number) {
  const miles = meters / 1609.344;
  if (miles < 1) {
    const feet = meters / 0.3048;
    return `${feet < 10 ? Number(feet.toPrecision(2)) : Math.round(feet).toLocaleString("en-US")} ft`;
  }
  return `${miles < 1000 ? Number(miles.toPrecision(3)).toLocaleString("en-US") : compact(miles, 1)} ${miles === 1 ? "mile" : "miles"}`;
}

export function paperStackContent(data: Dashboard, basis: EquivalentBasis = "total") {
  const { values, partial, detail } = equivalentSnapshot(data, basis);
  return `<strong title="${esc(detail)}">${values === null ? "—" : stackHeight(values.stack_meters)}</strong><span>paper stack${partial ? " · partial" : ""}</span>`;
}


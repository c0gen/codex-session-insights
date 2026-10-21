import type { Dashboard } from "../types";
import {
  equivalentSnapshot,
  type EquivalentBasis,
} from "../text-equivalents-data";

export type WorldId = "paper" | "library" | "trail" | "reading" | "vault";
export type Units = "imperial" | "metric";
export type Proportions = "readable" | "true";
export type ReadingSchedule = "continuous" | "30" | "60";
export type TrailView = "auto" | "unrolled" | "globe";
export interface WorldOptions {
  world: WorldId;
  units: Units;
  proportions: Proportions;
  landmark: string;
  readingSchedule: ReadingSchedule;
  trailView: TrailView;
}
export const WORLDS: {
  id: WorldId;
  title: string;
  subtitle: string;
  symbol: string;
}[] = [
  {
    id: "paper",
    title: "Paper Tower",
    subtitle: "From a sheet to the stratosphere",
    symbol: "▤",
  },
  {
    id: "library",
    title: "Infinite Library",
    subtitle: "A collection written in tokens",
    symbol: "▥",
  },
  {
    id: "trail",
    title: "Paper Trail",
    subtitle: "Lay it all out, end to end",
    symbol: "◎",
  },
  {
    id: "reading",
    title: "Reading Journey",
    subtitle: "One reader. A very long story.",
    symbol: "◷",
  },
  {
    id: "vault",
    title: "Floppy Vault",
    subtitle: "Your text, in a different era",
    symbol: "▣",
  },
];
export const EARTH_RADIUS_M = 6_371_000;
export const EARTH_CIRCUIT_M = 2 * Math.PI * EARTH_RADIUS_M;
export const SHEET_WIDTH_M = 0.2159,
  SHEET_LENGTH_M = 0.2794;
export const DEFAULT_OPTIONS: WorldOptions = {
  world: "paper",
  units: "imperial",
  proportions: "readable",
  landmark: "auto",
  readingSchedule: "continuous",
  trailView: "auto",
};

export function restoreWorldOptions(raw: string | null): WorldOptions {
  let value: Partial<WorldOptions> = {};
  try {
    value = JSON.parse(raw || "{}") || {};
  } catch {
    /* Defaults cover unavailable storage. */
  }
  return {
    world: WORLDS.some((w) => w.id === value.world) ? value.world! : "paper",
    units: value.units === "metric" ? "metric" : "imperial",
    proportions: value.proportions === "true" ? "true" : "readable",
    landmark: "auto",
    readingSchedule:
      value.readingSchedule === "30" || value.readingSchedule === "60"
        ? value.readingSchedule
        : "continuous",
    trailView: "auto",
  };
}

export function worldSnapshot(data: Dashboard, basis: EquivalentBasis) {
  const source = equivalentSnapshot(data, basis);
  const valid =
    source.tokens !== null &&
    Number.isFinite(source.tokens) &&
    source.tokens >= 0;
  const values = valid ? source.values : null;
  return {
    ...source,
    tokens: valid ? source.tokens : null,
    values,
    basis,
    detail: valid ? source.detail : "Token counters unavailable.",
    captureScope: imageScope(data, basis, source.detail.startsWith("All-time")),
    trailMetres: values ? values.pages * SHEET_LENGTH_M : null,
    readingMinutes: values ? (source.tokens! * 0.75) / 150 : null,
    demo: !!data.demo,
    saved: !!data.readonly,
  };
}
export type WorldSnapshot = ReturnType<typeof worldSnapshot>;

/** Share useful filter context without exposing account, source, model or project names. */
function imageScope(data: Dashboard, basis: EquivalentBasis, allTime: boolean) {
  if (allTime)
    return "All-time combined total; independent of dashboard filters.";
  const filters = data.filters;
  const dates = data.date_bounds;
  const interval =
    dates?.start &&
    dates.end &&
    /^\d{4}-\d{2}-\d{2}$/.test(dates.start) &&
    /^\d{4}-\d{2}-\d{2}$/.test(dates.end)
      ? `${dates.start} to ${dates.end}`
      : "Applied date range";
  const restrictions = [
    filters?.provider ? "selected tool" : "",
    filters?.project_id ? "selected project" : "",
    filters?.model ? "selected model" : "",
    filters?.source_id ? "selected source" : "",
  ].filter(Boolean);
  return `${data.readonly ? "Saved snapshot" : basis === "output" ? "Recorded output" : "Analyzed snapshot"} · ${interval}${restrictions.length ? " · " + restrictions.join(", ") : " · all tools and projects"}.`;
}

export const number = (n: number, digits = 2) =>
  n > 0 && n < 10 ** -digits
    ? n.toLocaleString("en-US", { maximumSignificantDigits: 2 })
    : n.toLocaleString("en-US", { maximumFractionDigits: digits });
export function distance(metres: number, units: Units) {
  if (units === "imperial")
    return metres < 0.3048
      ? `${number(metres / 0.0254)} in`
      : metres < 1609.344
        ? `${number(metres / 0.3048)} ft`
        : `${number(metres / 1609.344)} mi`;
  return metres < 1
    ? `${number(metres * 100, 3)} cm`
    : metres < 1000
      ? `${number(metres)} m`
      : `${number(metres / 1000)} km`;
}
export function duration(minutes: number) {
  return minutes < 60
    ? `${number(minutes)} minutes`
    : minutes < 1440
      ? `${number(minutes / 60)} hours`
      : minutes < 525960
        ? `${number(minutes / 1440)} days`
        : `${number(minutes / 525960)} years`;
}
export function readingElapsed(minutes: number, schedule: ReadingSchedule) {
  return schedule === "continuous"
    ? minutes
    : (minutes * 1440) / Number(schedule);
}
export function scheduleName(schedule: ReadingSchedule) {
  return schedule === "continuous"
    ? "continuous reading"
    : `${schedule} minutes/day`;
}
export function trailMode(metres: number, mode: TrailView) {
  return mode === "auto"
    ? metres < EARTH_CIRCUIT_M / 4
      ? "unrolled"
      : "globe"
    : mode;
}
export function exhibitMeasure(s: WorldSnapshot, o: WorldOptions) {
  if (!s.values)
    return {
      value: "Unavailable",
      label: "Token counters unavailable",
      explanation: s.detail,
    };
  const v = s.values;
  return {
    paper: {
      value: distance(v.stack_meters, o.units),
      label: `${number(v.pages, 0)} sheets of paper`,
      explanation:
        "500 words/sheet · 0.004 in thick · US Letter · single-sided, uncompressed",
    },
    library: {
      value: number(v.novels),
      label: "novel equivalents",
      explanation:
        "90,000 words/novel · 150 novels/bookcase · one detailed book = one novel equivalent",
    },
    trail: {
      value: distance(s.trailMetres!, o.units),
      label: `${number(s.trailMetres! / EARTH_CIRCUIT_M, 3)} trips around Earth`,
      explanation:
        "Sheets laid lengthwise · 27.94 cm/sheet · spherical Earth, radius 6,371 km",
    },
    reading: {
      value: duration(readingElapsed(s.readingMinutes!, o.readingSchedule)),
      label:
        o.readingSchedule === "continuous"
          ? "of continuous reading"
          : `elapsed at ${scheduleName(o.readingSchedule)}`,
      explanation: `Reading time: ${duration(s.readingMinutes!)} continuously · 150 words/minute · 365.25 days/year · corridor represents elapsed time`,
    },
    vault: {
      value: number(v.floppy_disks),
      label: "floppy-disk equivalents",
      explanation:
        "4 bytes/token ÷ 1,440,000 bytes/disk · illustrative text capacity, not measured storage",
    },
  }[o.world];
}

/** Counts are grouped before rendering, so geometry never grows with total usage. */
export function groupedCount(total: number, limit = 120) {
  if (!(total > 0)) return { unit: 1, count: 0, last: 0 };
  const unit = Math.max(1, Math.pow(10, Math.ceil(Math.log10(total / limit))));
  const count = Math.min(limit, Math.ceil(total / unit));
  return {
    unit,
    count,
    last: Math.max(0, Math.min(1, total / unit - count + 1)),
  };
}
